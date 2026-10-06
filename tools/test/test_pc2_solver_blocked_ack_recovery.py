"""Retry a lost blocked-report ACK without bypassing manual execution gates."""

from copy import deepcopy

import pytest

from tools import pc2_solver_fallback, pc2_solver_loop, pc2_solver_retry_state
from tools.pc2_solver_state_store import _default_fallback_state
from tools.test.pc2_loop_test_dependencies import patch_loop_dependency


@pytest.fixture
def blocked_loop(monkeypatch):
    state = _default_fallback_state()
    state.update(
        challenge_id="seed-one",
        scope="seed",
        slider_attempts=6,
        consecutive_failures=10,
        solver_cooldown_until=990.0,
        solver_cooldown_reason="repeated_solver_failures",
        node_solver_blocked_reported=False,
        node_solver_blocked_report_attempts=1,
        node_solver_blocked_report_next_retry_at=999.0,
        node_solver_blocked_report_last_error="Read timed out",
    )
    status = {
        "scope": "seed",
        "challenge_id": "seed-one",
        "paused": True,
        "running": False,
        "manual_required": True,
        "manual_only": True,
        "last_failure_reason": "repeated_solver_failures",
        "node_solver_blocked": True,
        "last_request": {
            "target_url": "https://sf.taobao.com/list/1.htm",
            "node_id": "pc2",
        },
    }
    events, reports, resumes, saved = [], [], [], []
    clock = [1000.0]
    response = [{"error": "Read timed out"}]

    def save(value):
        saved.append(deepcopy(value))

    def report(_api, value, fallback, *, expected_node_id):
        reports.append((deepcopy(value), deepcopy(fallback), expected_node_id))
        return response[0]

    patch_loop_dependency(monkeypatch, "prepare_solver_browser", lambda *_a: None)
    patch_loop_dependency(monkeypatch, "log_event", events.append)
    patch_loop_dependency(monkeypatch, "write_solver_heartbeat", lambda *_a: None)
    patch_loop_dependency(
        monkeypatch,
        "process_pending_control_actions",
        lambda **_kw: {
            "handled": False,
            "last_probe_target": None,
            "last_auth_confirmed_at": 0,
        },
    )
    patch_loop_dependency(monkeypatch, "read_solver_status", lambda _a: status)
    patch_loop_dependency(monkeypatch, "compact_active_challenge_pages", lambda *_a: {})
    patch_loop_dependency(
        monkeypatch, "reset_forced_solver_scopes", lambda _a, _b, value, _d: value
    )
    patch_loop_dependency(monkeypatch, "_load_fallback_state", lambda: state)
    patch_loop_dependency(monkeypatch, "_save_fallback_state", save)
    monkeypatch.setattr(pc2_solver_fallback, "_save_fallback_state", save)
    monkeypatch.setattr(pc2_solver_retry_state, "_save_fallback_state", save)
    monkeypatch.setattr(pc2_solver_fallback, "notify_solver_blocked", report)
    monkeypatch.setattr(pc2_solver_fallback, "SLIDER_RETRY_INTERVAL_SECONDS", 5.0)
    patch_loop_dependency(
        monkeypatch,
        "_retry_pending_collection_resume",
        lambda *_a, **kw: resumes.append(deepcopy(kw["state"])) or {},
    )
    for name in ("_reset_fallback_state", "run_solver_local_with_deadline"):
        patch_loop_dependency(
            monkeypatch, name, lambda *_a, **_kw: pytest.fail("must not reset or solve")
        )
    monkeypatch.setattr(pc2_solver_loop.time, "time", lambda: clock[0])
    monkeypatch.setattr(
        pc2_solver_loop.time, "sleep", lambda _a: (_ for _ in ()).throw(SystemExit())
    )

    def poll(now, result):
        clock[0], response[0] = now, result
        events.clear()
        with pytest.raises(SystemExit):
            pc2_solver_loop.local_solver_loop(poll_seconds=1, expected_node_id="pc2")
        return [event["kind"] for event in events]

    return state, status, reports, resumes, saved, poll


@pytest.mark.parametrize("until", [990.0, 1100.0])
def test_manual_gate_retries_lost_ack_before_cooldown_resume(blocked_loop, until):
    state, _status, reports, resumes, saved, poll = blocked_loop
    state["solver_cooldown_until"] = until
    budget = {
        key: state[key]
        for key in ("slider_attempts", "consecutive_failures", "solver_cooldown_until")
    }
    assert "node_solver_blocked_report" in poll(1000, {"error": "Read timed out"})
    assert len(reports) == 1
    assert state["node_solver_blocked_reported"] is False
    assert state["node_solver_blocked_report_next_retry_at"] == 1005.0
    assert state["collection_resume_pending"] is False
    assert resumes == []

    assert "waiting_for_manual_auth" in poll(1001, {"status": "node_solver_blocked"})
    assert len(reports) == 1  # Respect report backoff even after cooldown expiry.
    assert "waiting_for_manual_auth" in poll(1005, {"ok": True, "status": "accepted"})
    assert state["node_solver_blocked_reported"] is False
    assert state["collection_resume_pending"] is False
    assert resumes == []  # A generic 2xx response is not the required ACK.

    expected = "collection_resume_pending" if until < 1010 else "solver_cooldown_active"
    assert expected in poll(1010, {"status": "node_solver_blocked"})
    assert state["node_solver_blocked_reported"] is True
    assert state["node_solver_blocked_report_attempts"] == 4
    assert state["node_solver_blocked_report_last_error"] is None
    assert bool(resumes) is (until < 1010)
    assert len(reports) == 3
    assert all(report[2] == "pc2" for report in reports)
    assert saved and all(
        all(item[key] == value for key, value in budget.items()) for item in saved
    )
    assert expected in poll(1011, {"error": "must not report again"})
    assert len(reports) == 3


@pytest.mark.parametrize(
    "state_changes,status_changes",
    [
        ({}, {"last_failure_reason": "manual_required"}),
        ({}, {"challenge_id": "seed-new"}),
        ({}, {"scope": "detail"}),
        ({}, {"node_solver_blocked": False}),
        ({}, {"running": True}),
        ({}, {"last_request": {"node_id": "other"}}),
        ({"manual_pushed": True}, {}),
        ({"terminal_manual_pending": True}, {}),
        ({"solver_cooldown_reason": "manual_required"}, {}),
        ({"solver_cooldown_until": None}, {}),
    ],
)
def test_lost_ack_recovery_preserves_manual_and_owner_gates(
    blocked_loop, state_changes, status_changes
):
    state, status, reports, resumes, _saved, poll = blocked_loop
    state.update(state_changes)
    status.update(status_changes)
    assert "waiting_for_manual_auth" in poll(1000, {"status": "node_solver_blocked"})
    assert reports == []
    assert resumes == []
    assert state["node_solver_blocked_reported"] is False
    assert state["slider_attempts"] == 6
    assert state["consecutive_failures"] == 10
