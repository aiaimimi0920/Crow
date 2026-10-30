"""New completions cannot borrow a persisted challenge from an older request."""

from types import SimpleNamespace

import pytest

from src.auth_cleanup_completion import AuthCleanupCompletion
from tools import pc2_solver_auth as auth
from tools import pc2_solver_auth_pending as pending
from tools import pc2_solver_state_store as store

SEED = "https://sf.taobao.com/list/50025969__2.htm?page=18"
DETAIL = "https://sf-item.taobao.com/sf_item/123.htm"
BUDGET = {
    "consecutive_failures": 7,
    "slider_attempts": 9,
    "window_started_at": 100.0,
    "slider_next_attempt_at": 200.0,
    "solver_cooldown_until": 300.0,
    "solver_cooldown_reason": "repeated_solver_failures",
    "solver_cooldown_cycles": 2,
}


@pytest.mark.parametrize(
    ("old_target", "new_target", "scope"),
    [
        (SEED, DETAIL, "detail"),
        (DETAIL, SEED, "seed"),
        (DETAIL.replace("123.htm", "456.htm"), DETAIL, "detail"),
        (DETAIL, DETAIL, "detail"),
    ],
)
@pytest.mark.parametrize("challenge_id", [None, "", " \t ", " current "])
def test_new_completion_uses_only_its_explicit_challenge(
    old_target, new_target, scope, challenge_id
):
    old = store._default_fallback_state()
    old.update(
        BUDGET,
        challenge_id="obsolete",
        scope="seed" if old_target == SEED else "detail",
        auth_complete_pending=True,
        auth_completion_id="previous-completion",
        auth_complete_target_url=old_target,
        auth_complete_attempts=4,
        collection_resume_pending=True,
        collection_resume_request_id="old-resume",
    )
    store._save_fallback_state(old)

    result = pending._mark_auth_complete_pending(new_target, challenge_id=challenge_id)

    assert result == store._load_fallback_state()
    assert result["challenge_id"] == (
        "current" if challenge_id == " current " else None
    )
    assert result["scope"] == scope
    assert result["auth_complete_target_url"] == new_target
    assert result["auth_completion_id"] != "previous-completion"
    assert result["auth_complete_pending"] is True
    assert result["auth_complete_attempts"] == 0
    assert result["collection_resume_pending"] is False
    assert result["collection_resume_request_id"] is None
    assert {key: result[key] for key in BUDGET} == BUDGET


@pytest.mark.parametrize("challenge_id", [None, "current"])
def test_success_handoff_and_persisted_retry_keep_the_same_request(
    monkeypatch, challenge_id
):
    monkeypatch.setattr(pending, "log_event", lambda _event: None)
    monkeypatch.setattr(
        pending, "read_solver_status", lambda _api: {"error": "offline"}
    )
    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_ATTEMPTS", 1)
    old = store._default_fallback_state()
    old.update(BUDGET, challenge_id="obsolete", scope="seed")
    store._save_fallback_state(old)
    calls = []

    def post(_url, payload, *, timeout):
        calls.append(dict(payload))
        persisted = store._load_fallback_state()
        assert persisted["challenge_id"] == payload["challenge_id"] == challenge_id
        assert persisted["auth_completion_id"] == payload["completion_id"]
        assert payload["scope"] == "detail"
        assert timeout > 0
        raise TimeoutError("offline fixture")

    monkeypatch.setattr(auth, "post_json", post)
    first = pending.confirm_local_solver_success(
        "https://nas.test/api",
        {"challenge_id": challenge_id},
        DETAIL,
        "http://browser.test:9224",
        "pc2",
    )
    persisted = store._load_fallback_state()
    second = pending._retry_pending_auth_confirmation(
        "https://nas.test/api", now=float(persisted["auth_complete_next_retry_at"])
    )

    assert first["pending"] is second["pending"] is True
    assert first["confirmed"] is second["confirmed"] is False
    assert len(calls) == 2 and calls[0] == calls[1]
    assert calls[0]["challenge_id"] == challenge_id
    assert calls[0]["scope"] == "detail"
    persisted = store._load_fallback_state()
    assert persisted["auth_complete_attempts"] == 2
    assert persisted["auth_complete_target_url"] == DETAIL
    assert {key: persisted[key] for key in BUDGET} == BUDGET


def test_missing_current_id_cannot_reuse_old_state_to_pass_server_challenge_gate():
    old = store._default_fallback_state()
    old.update(challenge_id="obsolete", scope="seed")
    store._save_fallback_state(old)
    state = pending._mark_auth_complete_pending(DETAIL)
    active = {"challenge_id": "obsolete"}
    gate = SimpleNamespace(
        normalize_scope=lambda value: value,
        scope_status=lambda _scope: active,
    )
    payload = {"scope": state["scope"], "challenge_id": state["challenge_id"]}

    assert (
        AuthCleanupCompletion._node_auth_challenge_matches(
            gate, payload, "pc2_local_solver"
        )
        is False
    )
    active["challenge_id"] = None
    assert (
        AuthCleanupCompletion._node_auth_challenge_matches(
            gate, payload, "pc2_local_solver"
        )
        is True
    )
