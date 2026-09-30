"""Offline acceptance of stalled progress recovery without real Docker or NAS."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools.pc2_collection_controller import step
from tools.pc2_collection_progress import progress_sample
from tools.pc2_collection_progress_watchdog import CollectionProgressWatchdog
from tools.test.test_pc2_collection_watchdog import BrowserDocker


def status():
    return {
        "statistics": {"valid": True, "stale": False, "age_seconds": 1},
        "paused": False,
        "collection_scopes": {"seed": {"paused": False}, "detail": {"paused": False}},
        "auth_recovery": {"active": None},
        "captcha_solver": {"running": False},
        "captured_count": 10,
        "seed_occurrence_total": 20,
        "seed_scan_job_completed": 5,
        "seed_scan_progress_exhausted": 2,
        "raw_capture_pending_count": 3,
        "seed_scan_job_pending": 0,
        "seed_scan_job_in_progress": 0,
    }


class ProgressDocker(BrowserDocker):
    def __init__(self):
        super().__init__()
        self.row["State"]["Health"]["Status"] = "healthy"
        self.worker = deepcopy(self.row)
        self.worker.update(Id="b" * 64, Name="/fapaifang-pc2-detail-1")
        self.worker["Config"]["Labels"]["com.docker.compose.service"] = "pc2-detail-1"

    def __call__(self, args, **kwargs):
        if args[0] == "inspect":
            return json.dumps([self.row, self.worker])
        return super().__call__(args, **kwargs)


@pytest.fixture
def setup(tmp_path):
    docker, now, payload, calls = ProgressDocker(), [1000], status(), []
    session = SimpleNamespace(
        capture=lambda _: calls.append("capture") or {"path": "private"},
        restore=lambda *_: calls.append("restore"),
    )
    make = lambda: CollectionProgressWatchdog(
        tmp_path,
        runner=docker,
        clock=lambda: now[0],
        probe=lambda _: deepcopy(payload),
        session=session,
        stall=900,
        interval=60,
    )
    return docker, now, payload, calls, make


def advance(watcher, now, seconds):
    for _ in range(seconds // 60):
        now[0] += 60
        result = watcher.step()
    return result


def test_stall_restarts_exact_browser_and_restores_session(setup):
    docker, now, payload, calls, make = setup
    watcher = make()
    watcher.step()
    assert advance(watcher, now, 840) == "watching"
    assert not docker.restarts
    assert advance(watcher, now, 60) == "restart_requested"
    assert docker.restarts == ["a" * 64]
    assert calls == ["capture", "restore"]
    assert json.loads(watcher.path.read_text())["consecutive_attempts"] == 1


@pytest.mark.parametrize(
    "condition",
    [
        "paused",
        "challenge",
        "manual",
        "recovery",
        "solver",
        "idle",
        "stale",
        "missing",
        "stopped",
    ],
)
def test_waiting_and_invalid_evidence_never_restart(setup, condition):
    docker, now, payload, calls, make = setup
    if condition == "paused":
        payload["paused"] = True
    if condition == "challenge":
        payload["collection_scopes"]["detail"]["challenge_id"] = "active"
    if condition == "manual":
        payload["collection_scopes"]["seed"]["manual_required"] = True
    if condition == "recovery":
        payload["auth_recovery"]["active"] = {"status": "verifying"}
    if condition == "solver":
        payload["captcha_solver"]["running"] = True
    if condition == "idle":
        payload["raw_capture_pending_count"] = 0
    if condition == "stale":
        payload["statistics"]["stale"] = True
    if condition == "missing":
        del payload["captured_count"]
    if condition == "stopped":
        docker.row["State"]["Running"] = False
    watcher = make()
    watcher.step()
    advance(watcher, now, 1800)
    assert not docker.restarts and not calls


def test_data_progress_and_observation_gaps_reset_deadline(setup):
    docker, now, payload, calls, make = setup
    watcher = make()
    watcher.step()
    advance(watcher, now, 840)
    payload["captured_count"] += 1
    assert advance(watcher, now, 60) == "progress"
    advance(watcher, now, 840)
    now[0] += 600
    watcher.step()
    assert not docker.restarts
    assert advance(watcher, now, 900) == "restart_requested"


def test_persistent_cap_only_resets_after_real_progress(setup):
    docker, now, payload, calls, make = setup
    watcher = make()
    watcher.step()
    assert advance(watcher, now, 900) == "restart_requested"
    watcher = make()
    assert advance(watcher, now, 1800) == "restart_requested"
    watcher = make()
    assert advance(watcher, now, 3600) == "restart_limit_reached"
    assert len(docker.restarts) == 2
    payload["captured_count"] += 1
    assert advance(watcher, now, 60) == "progress"
    assert json.loads(watcher.path.read_text())["consecutive_attempts"] == 0


def test_fresh_pre_restart_challenge_prevents_disruption(setup):
    docker, now, payload, calls, make = setup
    watcher = make()
    watcher.step()
    advance(watcher, now, 840)
    watcher.session.capture = lambda _: (
        payload["collection_scopes"]["detail"].update(challenge_id="new") or {}
    )
    assert advance(watcher, now, 60) == "state_changed"
    assert not docker.restarts


def test_interrupted_or_corrupt_receipt_is_not_replayed(setup):
    docker, now, payload, calls, make = setup
    watcher = make()
    for value in (
        '{"result":"interrupted"}',
        '{"observed_at":NaN}',
        "[]",
        '{"counters":[true]}',
    ):
        watcher.path.write_text(value)
        watcher = make()
        assert watcher.step() in {"state_unavailable", "reconciliation_required"}
        assert watcher.path.read_text() == value
    assert not docker.restarts


def test_progress_watchdog_shares_controller_operation_guards(tmp_path, monkeypatch):
    from contextlib import nullcontext

    monkeypatch.setattr(
        "tools.pc2_collection_controller.operation_lock", lambda _: nullcontext()
    )
    calls = []
    settings = SimpleNamespace(
        journal=tmp_path / "settings", step=lambda: calls.append("settings")
    )
    restart = SimpleNamespace(
        journal=tmp_path / "restart", step=lambda: calls.append("restart")
    )
    watcher = SimpleNamespace(
        step=lambda: calls.append("progress") or "restart_requested"
    )
    step(tmp_path, settings, restart, progress_watchdog=watcher)
    assert calls == ["progress"]
    calls.clear()
    settings.journal.write_text("{}")
    step(tmp_path, settings, restart, progress_watchdog=watcher)
    assert calls == ["settings"]


def test_invalid_numeric_contract_fails_closed():
    value = status()
    value["statistics"]["age_seconds"] = float("nan")
    with pytest.raises(ValueError):
        progress_sample(value)
