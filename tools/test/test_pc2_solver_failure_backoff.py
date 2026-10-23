"""恢复调度 ACK 不是求解成功，跨轮失败退避必须持久保留。"""

import pytest

from tools import pc2_solver_auth_pending as auth
from tools import pc2_solver_fallback as fallback
from tools import pc2_solver_retry_state as retry
from tools import pc2_solver_state_store as store
from tools.test.pc2_local_solver_test_context import _confirmed_auth_payload


def resume(monkeypatch, state, now, *, stale=False):
    pending = fallback._mark_collection_resume_pending(state, now=now)
    monkeypatch.setattr(
        fallback,
        "notify_collection_resume_after_cooldown",
        lambda *args, **kwargs: {"stale_challenge": True} if stale else {"ok": True},
    )
    monkeypatch.setattr(
        fallback,
        "_resume_after_cooldown_response_confirmed",
        lambda result, request_id: result.get("ok") is True,
    )
    return fallback._retry_pending_collection_resume("http://unused", pending, now)[
        "state"
    ]


def test_repeated_failures_use_persisted_bounded_half_open_backoff(monkeypatch):
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 10)
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_SECONDS", 180.0)
    state = store._default_fallback_state()
    state.update(challenge_id="first", scope="detail")
    for _ in range(9):
        assert not retry._record_slider_attempt_failure(state, now=100)[
            "cooldown_started"
        ]
    assert retry._record_slider_attempt_failure(state, now=100)["cooldown_started"]
    assert state["solver_cooldown_until"] == 280
    for cycle, duration in enumerate((360, 720, 1440, 1800, 1800), start=2):
        now = state["solver_cooldown_until"]
        state = resume(monkeypatch, state, now)
        assert state["slider_attempts"] == 0
        assert state["solver_cooldown_until"] is None
        state, _ = retry._sync_challenge_state(state, f"next-{cycle}", "seed")
        state = store._load_fallback_state()
        assert state["solver_cooldown_cycles"] == cycle - 1
        assert retry._record_slider_attempt_failure(state, now=now)["cooldown_started"]
        assert state["solver_cooldown_until"] == now + duration
    retry._reset_fallback_state()  # 真实 auth ACK 使用的成功重置边界。
    assert store._load_fallback_state()["solver_cooldown_cycles"] == 0


@pytest.mark.parametrize("stale", [False, True])
def test_old_state_resume_does_not_erase_failure_history(monkeypatch, stale):
    state = store._default_fallback_state()
    state.pop("solver_cooldown_cycles", None)
    state.update(
        challenge_id="old",
        scope="detail",
        slider_attempts=10,
        solver_cooldown_until=1000,
        solver_cooldown_reason="repeated_solver_failures",
    )
    restored = resume(monkeypatch, state, 1000, stale=stale)
    assert restored["solver_cooldown_cycles"] == 1
    assert restored["collection_resume_pending"] is False
    assert restored["solver_cooldown_until"] is None
    assert store._load_fallback_state() == restored


def test_retrying_unconfirmed_resume_does_not_advance_cycle(monkeypatch):
    state = store._default_fallback_state()
    state.update(solver_cooldown_cycles=3)
    pending = fallback._mark_collection_resume_pending(state, now=100)
    monkeypatch.setattr(
        fallback, "notify_collection_resume_after_cooldown", lambda *a, **k: {}
    )
    result = fallback._retry_pending_collection_resume(
        "http://unused", pending, now=100
    )
    assert result["confirmed"] is False
    assert result["state"]["solver_cooldown_cycles"] == 3
    assert (
        result["state"]["collection_resume_request_id"]
        == pending["collection_resume_request_id"]
    )


@pytest.mark.parametrize("scope", [None, "detail"])
def test_automatic_expiry_preserves_backoff_cycles(scope):
    state = store._default_fallback_state()
    state.update(challenge_id="old", scope=scope, solver_cooldown_cycles=4)
    result = retry._reset_fallback_state(preserve_budget_from=state)
    assert result["solver_cooldown_cycles"] == 4


@pytest.mark.parametrize("old_scope,new_scope", [(None, "detail"), ("seed", None)])
def test_unknown_scope_rotation_keeps_browser_failure_cycles(old_scope, new_scope):
    state = store._default_fallback_state()
    state.update(challenge_id="old", scope=old_scope, solver_cooldown_cycles=3)
    result, changed = retry._sync_challenge_state(state, "new", new_scope)
    assert changed
    assert result["solver_cooldown_cycles"] == 3


@pytest.mark.parametrize("stale", [False, True])
def test_auth_ack_resets_history_only_for_confirmed_current_challenge(
    monkeypatch, stale
):
    state = store._default_fallback_state()
    state.update(
        challenge_id="current",
        scope="detail",
        solver_cooldown_cycles=3,
        auth_complete_pending=True,
        auth_completion_id="completion",
        last_success_at=100,
    )
    response = (
        {"stale_challenge": True} if stale else _confirmed_auth_payload("completion")
    )
    monkeypatch.setattr(auth, "notify_auth_complete", lambda *a, **k: response)
    result = auth._retry_pending_auth_confirmation("http://unused", state, now=101)
    assert result["confirmed"] is (not stale)
    assert result["state"]["solver_cooldown_cycles"] == (3 if stale else 0)
    assert result["state"]["challenge_id"] is None
