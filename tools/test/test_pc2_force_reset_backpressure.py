"""Age-based automatic resets must not bypass shared-browser backpressure."""

import pytest

from tools import pc2_local_solver as facade
from tools import pc2_solver_loop_control as control
from tools import pc2_solver_retry_state as retry
from tools import pc2_solver_state_store as store
from tools.test.pc2_loop_test_dependencies import patch_loop_dependency


def forced_status(scope, challenge="old", *, blocked=False):
    return {
        "paused": True,
        "running": False,
        "scopes": {
            scope: {
                "scope": scope,
                "challenge_id": challenge,
                "force_reset_required": True,
                "paused": True,
                "manual_required": blocked,
                "manual_only": blocked,
                "node_solver_blocked": blocked,
                "last_failure_reason": "repeated_solver_failures" if blocked else None,
                "last_request": {"node_id": "pc2"},
            }
        },
    }


def forbid_reset(*_args, **_kwargs):
    pytest.fail("Automatic reset must wait for cooldown and resume confirmation")


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("until", [1100.0, 1000.0, 900.0])
def test_auto_reset_defers_scheduled_cooldown_even_after_expiry(
    monkeypatch, scope, until
):
    state = store._default_fallback_state()
    state.update(
        challenge_id="old",
        scope=scope,
        slider_attempts=10,
        consecutive_failures=10,
        solver_cooldown_until=until,
        solver_cooldown_reason="repeated_solver_failures",
        node_solver_blocked_reported=True,
    )
    store._save_fallback_state(state)
    monkeypatch.setattr(control.time, "time", lambda: 1000.0)
    monkeypatch.setattr(control, "notify_force_reset", forbid_reset)
    monkeypatch.setattr(control, "close_challenge_pages_for_scope", forbid_reset)
    events = []
    monkeypatch.setattr(control, "log_event", events.append)
    status = forced_status(scope, blocked=True)
    assert (
        control.reset_forced_solver_scopes("api.test", "cdp.test", status, "pc2")
        is status
    )
    assert store._load_fallback_state() == state
    assert events[-1]["kind"] == "scoped_challenge_force_reset_deferred"
    assert events[-1]["cooldown_until"] == until


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("attempts,failures", [(8, 4), (4, 8)])
def test_auto_reset_expires_receipts_but_keeps_budget_and_lineage(
    monkeypatch, scope, attempts, failures
):
    state = store._default_fallback_state()
    state.update(
        challenge_id="old",
        scope=scope,
        slider_attempts=attempts,
        consecutive_failures=failures,
        window_started_at=100.0,
        slider_next_attempt_at=200.0,
        auth_complete_pending=True,
        auth_completion_id="old-auth",
        collection_resume_pending=True,
        collection_resume_request_id="old-resume",
        terminal_manual_pending=True,
        manual_pushed=True,
        last_success_at=90.0,
    )
    before = dict(state)
    store._save_fallback_state(state)
    monkeypatch.setattr(
        control, "notify_force_reset", lambda *_a: {"force_reset": True}
    )
    monkeypatch.setattr(control, "close_challenge_pages_for_scope", lambda *_a: {})
    monkeypatch.setattr(control, "read_solver_status", lambda _: {})
    monkeypatch.setattr(control, "log_event", lambda _: None)
    control.reset_forced_solver_scopes(
        "api.test", "cdp.test", forced_status(scope), "pc2"
    )
    expected = store._default_fallback_state()
    expected.update(
        challenge_id="old",
        scope=scope,
        consecutive_failures=8,
        window_started_at=100.0,
        slider_next_attempt_at=200.0,
    )
    assert store._load_fallback_state() == expected
    assert state == before


def test_seed_eight_auto_reset_detail_two_reaches_cooldown(monkeypatch):
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 10)
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_SECONDS", 180.0)
    monkeypatch.setattr(
        control, "notify_force_reset", lambda *_a: {"force_reset": True}
    )
    monkeypatch.setattr(control, "close_challenge_pages_for_scope", lambda *_a: {})
    monkeypatch.setattr(control, "read_solver_status", lambda _: {})
    monkeypatch.setattr(control, "log_event", lambda _: None)
    state, _ = retry._sync_challenge_state(
        store._default_fallback_state(), "old", "seed"
    )
    for index in range(8):
        retry._record_slider_attempt_failure(state, now=100.0 + index)
    store._save_fallback_state(state)
    control.reset_forced_solver_scopes(
        "api.test", "cdp.test", forced_status("seed"), "pc2"
    )
    state, _ = retry._sync_challenge_state(
        store._load_fallback_state(), "new", "detail"
    )
    assert state["slider_attempts"] == 0 and state["consecutive_failures"] == 8
    for index in range(2):
        retry._record_slider_attempt_failure(state, now=200.0 + index)
    assert state["slider_attempts"] == 2 and state["consecutive_failures"] == 10
    assert state["solver_cooldown_until"] == 381.0


@pytest.mark.parametrize(
    "until,expected",
    [(1100.0, "solver_cooldown_active"), (900.0, "collection_resume_pending")],
)
def test_real_loop_defers_force_reset_and_reaches_existing_resume_path(
    monkeypatch, until, expected
):
    state = store._default_fallback_state()
    state.update(
        challenge_id="old",
        scope="detail",
        slider_attempts=10,
        consecutive_failures=10,
        solver_cooldown_until=until,
        solver_cooldown_reason="repeated_solver_failures",
        node_solver_blocked_reported=True,
    )
    store._save_fallback_state(state)
    status = forced_status("detail", blocked=True)
    events, resumed = [], []
    for name, value in (
        ("log_event", lambda event: events.append(event["kind"])),
        ("write_solver_heartbeat", lambda *_a, **_k: None),
        ("check_cdp_healthy", lambda _: True),
        (
            "process_pending_control_actions",
            lambda **_k: {
                "handled": False,
                "last_probe_target": None,
                "last_auth_confirmed_at": 0,
            },
        ),
        ("read_solver_status", lambda _: status),
        ("compact_active_challenge_pages", lambda *_a: {}),
        ("close_challenge_pages_for_scope", forbid_reset),
        ("notify_force_reset", forbid_reset),
        ("_retry_pending_collection_resume", lambda *_a, **_k: resumed.append(1) or {}),
        ("run_solver_local_with_deadline", forbid_reset),
    ):
        patch_loop_dependency(monkeypatch, name, value)
    monkeypatch.setattr(facade.time, "time", lambda: 1000.0)
    monkeypatch.setattr(
        facade.time, "sleep", lambda _: (_ for _ in ()).throw(SystemExit())
    )
    with pytest.raises(SystemExit):
        facade.local_solver_loop(poll_seconds=1, expected_node_id="pc2")
    assert "scoped_challenge_force_reset_deferred" in events
    assert expected in events
    assert bool(resumed) is (expected == "collection_resume_pending")
    saved = store._load_fallback_state()
    assert saved["solver_cooldown_until"] == until
    assert saved["collection_resume_pending"] is bool(resumed)
