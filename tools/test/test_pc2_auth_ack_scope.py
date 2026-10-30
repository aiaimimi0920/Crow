"""An explicit request scope owns its ACK and local retry state."""

from copy import deepcopy

import pytest

from tools import pc2_solver_auth as auth
from tools import pc2_solver_auth_pending as pending
from tools import pc2_solver_retry_state as retry


def confirmed(scope="detail"):
    return {
        "ok": True,
        "auth_state_confirmed": True,
        "completion_id": "completion-fixture",
        "scope": scope,
        "scope_paused": False,
        "scope_manual_required": False,
        "scope_force_unlock_flag_exists": False,
        "captcha_solver": {
            "paused": True,
            "manual_required": True,
            "scopes": {scope: {"paused": False, "manual_required": False}},
        },
    }


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("returned_scope", ["other", None, "", "unknown"])
def test_wrong_scope_ack_preserves_pending_budget(monkeypatch, scope, returned_scope):
    if returned_scope == "other":
        returned_scope = "seed" if scope == "detail" else "detail"
    response = confirmed(returned_scope)
    if returned_scope not in {"seed", "detail"}:
        response.update(
            paused=False,
            captcha_solver={
                "paused": False,
                "manual_required": False,
                "force_unlock_flag_exists": False,
            },
        )
    saved, reset, requests = [], [], []
    state = {
        "auth_complete_pending": True,
        "auth_completion_id": "completion-fixture",
        "auth_complete_attempts": 2,
        "scope": scope,
        "challenge_id": "challenge-fixture",
        "consecutive_failures": 7,
        "slider_attempts": 4,
        "solver_cooldown_until": 2000,
        "solver_cooldown_cycles": 2,
    }

    def notify(*args, **kwargs):
        requests.append(kwargs)
        return {**response, "request_attempts": 1}

    monkeypatch.setattr(pending, "notify_auth_complete", notify)
    monkeypatch.setattr(
        pending, "_reset_fallback_state", lambda: reset.append(True) or {}
    )
    monkeypatch.setattr(
        pending, "_save_fallback_state", lambda s: saved.append(deepcopy(s))
    )
    monkeypatch.setattr(retry, "AUTH_COMPLETE_RETRY_BASE_SECONDS", 5)
    monkeypatch.setattr(retry, "AUTH_COMPLETE_RETRY_MAX_SECONDS", 60)

    result = pending._retry_pending_auth_confirmation(
        "http://fixture.invalid/api", state=state, now=1000
    )

    assert result["confirmed"] is False
    assert result["pending"] is True
    assert reset == []
    assert requests[0]["scope"] == scope
    assert saved[-1]["auth_complete_attempts"] == 3
    assert saved[-1]["auth_complete_next_retry_at"] == 1020
    for key in (
        "auth_completion_id",
        "scope",
        "challenge_id",
        "consecutive_failures",
        "slider_attempts",
        "solver_cooldown_until",
        "solver_cooldown_cycles",
    ):
        assert saved[-1][key] == state[key]


@pytest.mark.parametrize("scope", ["seed", "detail"])
def test_notify_does_not_stop_on_another_scope_ack(monkeypatch, scope):
    calls = []
    other = "seed" if scope == "detail" else "detail"

    def post(*args, **kwargs):
        calls.append(True)
        return confirmed(other if len(calls) == 1 else scope)

    monkeypatch.setattr(auth, "post_json", post)
    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_ATTEMPTS", 3)
    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS", 0)

    result = auth.notify_auth_complete(
        "http://fixture.invalid/api",
        completion_id="completion-fixture",
        challenge_id="challenge-fixture",
        scope=scope,
    )

    assert len(calls) == result["request_attempts"] == 2
    assert result["scope"] == scope


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("idempotent", [False, True])
def test_matching_ack_accepts_only_its_scope_with_other_scope_paused(
    monkeypatch, scope, idempotent
):
    response = {**confirmed(scope), "idempotent": idempotent}
    monkeypatch.setattr(pending, "notify_auth_complete", lambda *a, **kw: response)
    monkeypatch.setattr(pending, "_reset_fallback_state", lambda: {"reset": True})
    result = pending._retry_pending_auth_confirmation(
        "http://fixture.invalid/api",
        state={
            "auth_complete_pending": True,
            "auth_completion_id": "completion-fixture",
            "scope": scope,
            "challenge_id": "challenge-fixture",
        },
        now=1000,
    )
    assert result["confirmed"] is True
    assert result["state"] == {"reset": True}


def test_legacy_pending_target_inference_has_the_same_scope_guard(monkeypatch):
    reset = []
    monkeypatch.setattr(
        pending, "notify_auth_complete", lambda *a, **kw: confirmed("seed")
    )
    monkeypatch.setattr(
        pending, "_reset_fallback_state", lambda: reset.append(True) or {}
    )
    monkeypatch.setattr(pending, "_save_fallback_state", lambda state: None)
    result = pending._retry_pending_auth_confirmation(
        "http://fixture.invalid/api",
        state={
            "auth_complete_pending": True,
            "auth_completion_id": "completion-fixture",
            "auth_complete_target_url": "https://sf-item.taobao.com/sf_item/123.htm",
        },
        now=1000,
    )
    assert result["confirmed"] is False
    assert result["pending"] is True
    assert reset == []


@pytest.mark.parametrize("scope", [None, ""])
def test_unscoped_legacy_confirmation_remains_supported(monkeypatch, scope):
    response = confirmed(None)
    response.update(
        paused=False,
        captcha_solver={
            "paused": False,
            "manual_required": False,
            "force_unlock_flag_exists": False,
        },
    )
    monkeypatch.setattr(auth, "post_json", lambda *a, **kw: response)
    result = auth.notify_auth_complete(
        "http://fixture.invalid/api",
        completion_id="completion-fixture",
        scope=scope,
    )
    assert result["request_attempts"] == 1
    assert result["auth_state_confirmed"] is True
