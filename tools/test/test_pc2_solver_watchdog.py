from __future__ import annotations

import json
import signal

import pytest

from tools import pc2_linux_healthcheck, pc2_solver_watchdog


def _write_heartbeat(path, updated_at_epoch: float) -> None:
    path.write_text(
        json.dumps({"pid": 1, "phase": "polling", "updated_at_epoch": updated_at_epoch}),
        encoding="utf-8",
    )


def test_watchdog_keeps_fresh_heartbeat_running(tmp_path) -> None:
    heartbeat_path = tmp_path / "heartbeat.json"
    _write_heartbeat(heartbeat_path, 980.0)
    signals: list[tuple[int, int]] = []

    result = pc2_solver_watchdog.watchdog_iteration(
        heartbeat_path,
        started_at=900.0,
        stale_seconds=300.0,
        startup_grace_seconds=180.0,
        parent_pid=1,
        now=1000.0,
        terminate=lambda pid, sig: signals.append((pid, sig)),
    )

    assert result == {"status": "healthy", "heartbeat_age_seconds": 20.0}
    assert signals == []


def test_watchdog_allows_missing_heartbeat_during_startup_grace(tmp_path) -> None:
    result = pc2_solver_watchdog.watchdog_iteration(
        tmp_path / "missing.json",
        started_at=900.0,
        stale_seconds=300.0,
        startup_grace_seconds=180.0,
        parent_pid=1,
        now=1000.0,
        terminate=lambda *_args: pytest.fail("startup grace must not restart PID 1"),
    )

    assert result == {"status": "startup_grace", "heartbeat_age_seconds": None}


def test_watchdog_terminates_parent_for_stale_heartbeat(tmp_path) -> None:
    heartbeat_path = tmp_path / "heartbeat.json"
    _write_heartbeat(heartbeat_path, 600.0)
    order: list[str] = []
    signals: list[tuple[int, int]] = []
    events: list[dict[str, object]] = []

    result = pc2_solver_watchdog.watchdog_iteration(
        heartbeat_path,
        started_at=500.0,
        stale_seconds=300.0,
        startup_grace_seconds=180.0,
        parent_pid=1,
        now=1000.0,
        terminate=lambda pid, sig: (
            order.append("terminate"),
            signals.append((pid, sig)),
        ),
        log=lambda event: (order.append("log"), events.append(event)),
    )

    assert result == {
        "status": "restart_requested",
        "heartbeat_age_seconds": 400.0,
        "parent_pid": 1,
    }
    assert signals == [(1, signal.SIGTERM)]
    assert order == ["log", "terminate"]
    assert events[0]["kind"] == "local_solver_watchdog_restart"


def test_browser_healthcheck_rejects_stale_or_missing_heartbeat(tmp_path) -> None:
    heartbeat_path = tmp_path / "heartbeat.json"

    with pytest.raises(RuntimeError, match="missing or invalid"):
        pc2_linux_healthcheck._check_solver_heartbeat(
            heartbeat_path,
            stale_seconds=300.0,
            now=1000.0,
        )

    _write_heartbeat(heartbeat_path, 600.0)
    with pytest.raises(RuntimeError, match="heartbeat is stale"):
        pc2_linux_healthcheck._check_solver_heartbeat(
            heartbeat_path,
            stale_seconds=300.0,
            now=1000.0,
        )

    _write_heartbeat(heartbeat_path, 900.0)
    pc2_linux_healthcheck._check_solver_heartbeat(
        heartbeat_path,
        stale_seconds=300.0,
        now=1000.0,
    )
