import json
import signal
from pathlib import Path

import pytest

from tools import pc2_solver_tab_guard as guard
from tools import pc2_solver_watchdog as watchdog


def inventory(count):
    return json.dumps(
        [
            {"type": "page", "id": str(i), "url": "https://private.invalid/"}
            for i in range(count)
        ]
        + [
            {"type": "service_worker", "id": "worker"},
            {"type": "iframe", "id": "frame"},
        ]
    ).encode()


@pytest.mark.parametrize("count", [0, 1, 4, 5, 8])
def test_threshold_closes_all_page_types_and_restarts_only_on_overflow(count):
    calls, signals, events = [], [], []

    def request(path, timeout):
        calls.append(path)
        assert 0 < timeout <= 2
        return inventory(count) if path == "/json/list" else b"Target is closing"

    result = guard.guard_iteration(
        123,
        request=request,
        terminate=lambda *args: signals.append(args),
        log=events.append,
    )
    assert calls == ["/json/list"] + (
        [f"/json/close/{i}" for i in range(count)] if count > 4 else []
    )
    assert signals == ([(123, signal.SIGTERM)] if count > 4 else [])
    assert result["status"] == ("restart_requested" if count > 4 else "within_limit")
    assert "private.invalid" not in json.dumps(events)
    if count > 4:
        assert result["close_acknowledged"] == count


@pytest.mark.parametrize(
    "payload", [b"{}", b"invalid", b"[null]", b'[{"type":"page"}]']
)
def test_invalid_inventory_never_guesses_overflow(payload):
    result = guard.guard_iteration(
        123,
        request=lambda *args: payload,
        terminate=lambda *args: pytest.fail("no verified overflow"),
        log=lambda event: None,
    )
    assert result["status"] == "unavailable"


def test_unreachable_inventory_leaves_existing_heartbeat_watchdog_in_charge():
    def request(*args):
        raise TimeoutError("private endpoint detail")

    events = []
    assert (
        guard.guard_iteration(
            123,
            request=request,
            terminate=lambda *args: pytest.fail("not overflow"),
            log=events.append,
        )["status"]
        == "unavailable"
    )
    assert events == [
        {"kind": "browser_tab_guard_unavailable", "error_type": "TimeoutError"}
    ]


def test_close_failures_and_total_deadline_still_restart_supervisor():
    now, calls, signals, events = [0.0], [], [], []

    def request(path, timeout):
        calls.append(path)
        if path == "/json/list":
            return inventory(50)
        now[0] += timeout
        raise TimeoutError("stalled renderer")

    result = guard.guard_iteration(
        123,
        request=request,
        clock=lambda: now[0],
        terminate=lambda *args: signals.append((args, len(events))),
        log=events.append,
    )
    assert now[0] == 10
    assert len(calls) == 6
    assert result["close_failed"] == 5
    assert result["close_unattempted"] == 45
    assert signals == [((123, signal.SIGTERM), 2)]


def test_close_negative_ack_is_not_reported_as_closed():
    result = guard.guard_iteration(
        123,
        request=lambda path, timeout: (
            inventory(5) if path == "/json/list" else b"No such target id"
        ),
        terminate=lambda *args: None,
        log=lambda event: None,
    )
    assert result["close_acknowledged"] == 0
    assert result["close_failed"] == 5
    assert result["status"] == "restart_requested"


def test_overflow_guard_runs_before_heartbeat_even_during_startup(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        watchdog, "guard_iteration", lambda pid: {"status": "restart_requested"}
    )
    monkeypatch.setattr(
        watchdog,
        "watchdog_iteration",
        lambda *a, **kw: pytest.fail("overflow already handled"),
    )
    assert (
        watchdog.run_watchdog(
            tmp_path / "missing.json",
            stale_seconds=300,
            startup_grace_seconds=180,
            poll_seconds=30,
            parent_pid=123,
            browser_tab_guard=True,
        )
        == 0
    )


def test_guard_unavailable_does_not_disable_stale_heartbeat_restart(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        watchdog, "guard_iteration", lambda pid: {"status": "unavailable"}
    )
    monkeypatch.setattr(
        watchdog, "watchdog_iteration", lambda *a, **kw: {"status": "restart_requested"}
    )
    assert (
        watchdog.run_watchdog(
            tmp_path / "missing.json",
            stale_seconds=300,
            startup_grace_seconds=180,
            poll_seconds=30,
            parent_pid=123,
            browser_tab_guard=True,
        )
        == 0
    )


def test_container_launcher_enables_private_guard():
    root = Path(__file__).resolve().parents[2]
    launcher = (root / "ops/pc2-linux/start-browser-solver.sh").read_text(
        encoding="utf-8"
    )
    assert (
        "python tools/pc2_solver_watchdog.py \\\n  --browser-tab-guard \\" in launcher
    )
    assert guard.ENDPOINT == "http://127.0.0.1:9223"


def test_enabled_guard_polls_at_most_every_five_seconds(monkeypatch, tmp_path):
    monkeypatch.setattr(
        watchdog, "guard_iteration", lambda pid: {"status": "within_limit"}
    )
    monkeypatch.setattr(
        watchdog, "watchdog_iteration", lambda *a, **kw: {"status": "healthy"}
    )
    sleeps = []

    def sleep(value):
        sleeps.append(value)
        raise InterruptedError("stop test loop")

    monkeypatch.setattr(watchdog.time, "sleep", sleep)
    with pytest.raises(InterruptedError):
        watchdog.run_watchdog(
            tmp_path / "missing.json",
            stale_seconds=300,
            startup_grace_seconds=180,
            poll_seconds=30,
            parent_pid=123,
            browser_tab_guard=True,
        )
    assert sleeps == [5]
