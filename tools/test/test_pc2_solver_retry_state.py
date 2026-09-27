"""Native retry transitions retain identity and persistence ordering."""

from tools import pc2_solver_retry_state as retry
from tools import pc2_solver_state_store as store


def test_retry_functions_keep_native_identity_and_isolated_state_path(tmp_path):
    from tools import pc2_local_solver, pc2_solver_fallback

    assert store.FALLBACK_STATE_PATH.parent == tmp_path
    for name in retry.__all__:
        original = getattr(retry, name)
        if not callable(original):
            continue
        assert getattr(pc2_local_solver, name) is original
        assert getattr(pc2_solver_fallback, name) is original
        assert original.__globals__ is vars(retry)


def test_same_challenge_updates_scope_without_resetting_attempts():
    state = store._default_fallback_state()
    state.update(challenge_id="existing", slider_attempts=4, scope="seed")
    updated, reset = retry._sync_challenge_state(state, " existing ", "detail")
    assert updated is state
    assert not reset
    assert updated["slider_attempts"] == 4
    assert store._load_fallback_state()["scope"] == "detail"


def test_empty_or_unchanged_challenge_does_not_write(monkeypatch):
    calls = []
    monkeypatch.setattr(retry, "_save_fallback_state", calls.append)
    state = store._default_fallback_state()
    state.update(challenge_id="same", scope="seed")
    for challenge, scope in (("", "detail"), ("same", None), ("same", "seed")):
        result, reset = retry._sync_challenge_state(state, challenge, scope)
        assert result is state
        assert not reset
    assert calls == []
    assert state["scope"] == "seed"


def test_rotated_challenge_resets_pending_state_without_mutating_old_snapshot():
    state = store._default_fallback_state()
    state.update(challenge_id="old", auth_complete_pending=True, slider_attempts=8)
    result, reset = retry._sync_challenge_state(state, "new", "detail")
    assert reset and result is not state
    assert state["challenge_id"] == "old"
    assert state["auth_complete_pending"] is True
    assert result["auth_complete_pending"] is False
    assert result["slider_attempts"] == 0
    assert store._load_fallback_state() == result


def test_attempt_start_persists_but_failure_waits_for_caller_commit(monkeypatch):
    saved = []
    monkeypatch.setattr(
        retry, "_save_fallback_state", lambda state: saved.append(dict(state))
    )
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 1)
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_SECONDS", 30.0)
    state = store._default_fallback_state()
    assert retry._record_slider_attempt_started(state, now=100.0) is state
    result = retry._record_slider_attempt_failure(state, now=101.0)
    assert result["cooldown_started"] is True
    assert state["slider_attempt_started_at"] is None
    assert state["solver_cooldown_until"] == 131.0
    assert len(saved) == 1
    assert saved[0]["slider_attempt_started_at"] == 100.0
    assert saved[0]["slider_attempts"] == 0
    assert retry._solver_cooldown_active(state, now=130.9)
    assert not retry._solver_cooldown_active(state, now=131.0)


def test_reset_persists_fresh_default_state():
    store._save_fallback_state({"challenge_id": "previous", "slider_attempts": 9})
    result = retry._reset_fallback_state()
    assert result == store._default_fallback_state()
    assert store._load_fallback_state() == result
