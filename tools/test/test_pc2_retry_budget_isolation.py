"""A shared browser's failure budget survives scoped generation changes."""

import pytest

from tools import pc2_solver_loop_control as control
from tools import pc2_solver_loop_failure as failure
from tools import pc2_solver_retry_state as retry
from tools import pc2_solver_state_store as store

BUDGET = {
    "consecutive_failures": 8,
    "window_started_at": 100.0,
    "slider_next_attempt_at": 200.0,
    "solver_cooldown_until": 400.0,
    "solver_cooldown_reason": "repeated_solver_failures",
}


@pytest.mark.parametrize("old_scope", ["seed", "detail"])
@pytest.mark.parametrize("new_scope", ["seed", "detail", " seed "])
def test_known_generation_switch_keeps_budget_not_receipts(old_scope, new_scope):
    state = store._default_fallback_state()
    state.update(
        BUDGET,
        challenge_id="old",
        scope=old_scope,
        slider_attempts=8,
        auth_complete_pending=True,
        auth_completion_id="old-completion",
        node_solver_blocked_reported=True,
        node_solver_blocked_report_attempts=3,
        collection_resume_pending=True,
        collection_resume_request_id="old-resume",
        manual_pushed=True,
        terminal_manual_pending=True,
        last_success_at=90.0,
        slider_attempt_started_at=120.0,
    )
    before = dict(state)

    result, reset = retry._sync_challenge_state(state, "new", new_scope)

    expected = store._default_fallback_state()
    expected.update(BUDGET, challenge_id="new", scope=new_scope.strip())
    assert reset and result == expected
    assert state == before and result is not state
    assert store._load_fallback_state() == expected


@pytest.mark.parametrize(
    "old_scope,new_scope", [(None, "seed"), ("seed", None), ("other", "detail")]
)
def test_unknown_generation_switch_keeps_legacy_reset(old_scope, new_scope):
    state = store._default_fallback_state()
    state.update(BUDGET, challenge_id="old", scope=old_scope, slider_attempts=8)
    result, reset = retry._sync_challenge_state(state, "new", new_scope)
    expected = store._default_fallback_state()
    expected.update(challenge_id="new", scope=new_scope)
    assert reset and result == expected


def test_seed_eight_then_detail_two_reaches_existing_cooldown(monkeypatch):
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 10)
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_SECONDS", 180.0)
    monkeypatch.setattr(failure, "rotate_failed_challenge_target", lambda *_a, **_k: {})
    monkeypatch.setattr(failure, "manual_fallback_enabled", lambda: False)
    monkeypatch.setattr(failure, "log_event", lambda _: None)
    monkeypatch.setattr(failure.time, "time", lambda: 1000.0)
    state = store._default_fallback_state()
    state, _ = retry._sync_challenge_state(state, "seed-one", "seed")
    for _ in range(8):
        failure.record_failed_attempt("api.test", "cdp.test", "target.test", None)
    state = store._load_fallback_state()
    assert state["slider_attempts"] == state["consecutive_failures"] == 8
    state, _ = retry._sync_challenge_state(state, "detail-one", "detail")
    assert state["slider_attempts"] == 0
    for _ in range(2):
        failure.record_failed_attempt("api.test", "cdp.test", "target.test", None)
    state = store._load_fallback_state()
    assert state["slider_attempts"] == 2
    assert state["consecutive_failures"] == 10
    assert state["solver_cooldown_until"] == 1180.0
    state, _ = retry._sync_challenge_state(state, "seed-two", "seed")
    assert state["slider_attempts"] == 0
    assert retry._solver_cooldown_active(state, now=1100.0)
    assert state["solver_cooldown_until"] == 1180.0
    assert not retry._begin_solver_cooldown_if_needed(state, now=1100.0)


@pytest.mark.parametrize("attempts,failures", [(10, 0), (0, 10), (2, 10)])
def test_cooldown_respects_larger_legacy_or_shared_counter(
    monkeypatch, attempts, failures
):
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 10)
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_SECONDS", 180.0)
    state = store._default_fallback_state()
    state.update(slider_attempts=attempts, consecutive_failures=failures)
    assert retry._begin_solver_cooldown_if_needed(state, now=1000.0)
    assert state["solver_cooldown_until"] == 1180.0


def test_explicit_reset_clears_shared_budget():
    state = store._default_fallback_state()
    state.update(BUDGET, challenge_id="old", scope="seed")
    store._save_fallback_state(state)
    assert retry._reset_fallback_state() == store._default_fallback_state()


@pytest.mark.parametrize(
    "scope,challenge,confirmed,changes_during_call,should_expire",
    [
        ("seed", "old", True, False, True),
        ("seed", "old", False, False, False),
        ("detail", "old", True, False, False),
        ("seed", "other", True, False, False),
        ("seed", "old", True, True, False),
    ],
)
def test_force_reset_only_expires_acknowledged_matching_generation(
    monkeypatch, scope, challenge, confirmed, changes_during_call, should_expire
):
    state = store._default_fallback_state()
    state.update(
        BUDGET,
        challenge_id=challenge,
        scope=scope,
        solver_cooldown_until=None,
        solver_cooldown_reason=None,
        auth_complete_pending=True,
    )
    store._save_fallback_state(state)
    status = {
        "scopes": {
            "seed": {
                "force_reset_required": True,
                "challenge_id": "old",
                "last_request": {"node_id": "pc2"},
            }
        }
    }

    def acknowledge(*_args):
        if changes_during_call:
            state["challenge_id"] = "new"
            store._save_fallback_state(state)
        return {"force_reset": confirmed}

    monkeypatch.setattr(control, "notify_force_reset", acknowledge)
    monkeypatch.setattr(control, "close_challenge_pages_for_scope", lambda *_a: {})
    monkeypatch.setattr(control, "read_solver_status", lambda _: {})
    monkeypatch.setattr(control, "log_event", lambda _: None)
    control.reset_forced_solver_scopes("api.test", "cdp.test", status, "pc2")
    expected = dict(state)
    if should_expire:
        expected["auth_complete_pending"] = False
    assert store._load_fallback_state() == expected


def test_force_reset_without_generation_does_not_clear_budget(monkeypatch):
    state = store._default_fallback_state()
    state.update(BUDGET, scope="seed")
    store._save_fallback_state(state)
    status = {"scopes": {"seed": {"force_reset_required": True}}}
    monkeypatch.setattr(
        control, "notify_force_reset", lambda *_a: {"force_reset": True}
    )
    monkeypatch.setattr(control, "close_challenge_pages_for_scope", lambda *_a: {})
    monkeypatch.setattr(control, "read_solver_status", lambda _: {})
    monkeypatch.setattr(control, "log_event", lambda _: None)
    control.reset_forced_solver_scopes("api.test", "cdp.test", status, "pc2")
    assert store._load_fallback_state() == state


@pytest.mark.parametrize("scope", ["", "other", None])
def test_force_reset_without_known_scope_does_not_clear_budget(monkeypatch, scope):
    state = store._default_fallback_state()
    state.update(BUDGET, challenge_id="old", scope=scope)
    store._save_fallback_state(state)
    state = store._load_fallback_state()
    status = {"scopes": {scope: {"challenge_id": "old", "force_reset_required": True}}}
    monkeypatch.setattr(
        control, "notify_force_reset", lambda *_a: {"force_reset": True}
    )
    monkeypatch.setattr(control, "close_challenge_pages_for_scope", lambda *_a: {})
    monkeypatch.setattr(control, "read_solver_status", lambda _: {})
    monkeypatch.setattr(control, "log_event", lambda _: None)
    control.reset_forced_solver_scopes("api.test", "cdp.test", status, "pc2")
    assert store._load_fallback_state() == state
