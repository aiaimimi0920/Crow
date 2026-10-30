"""Accepted asynchronous refreshes are pending, not failed transport attempts."""

from copy import deepcopy

import pytest

from tools import pc2_solver_auth as auth
from tools import pc2_solver_auth_pending as pending
from tools import pc2_solver_retry_state as retry


def accepted(scope="detail"):
    return {
        "ok": True,
        "completion_id": "completion-1",
        "scope": scope,
        "auth_state_confirmed": False,
        "scope_paused": True,
        "scope_manual_required": False,
        "cookie_snapshot": {
            "status": "running",
            "completion_id": "completion-1",
            "expected_challenge_id": "challenge-1",
            "scope": scope,
            "refreshed": False,
        },
    }


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("status", ["pending", "running"])
def test_same_completion_refresh_waits_without_duplicate_posts(
    monkeypatch, scope, status
):
    calls = []
    response = accepted(scope)
    response["cookie_snapshot"]["status"] = status
    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_ATTEMPTS", 3)
    monkeypatch.setattr(
        auth, "post_json", lambda *a, **kw: calls.append(kw) or response
    )
    monkeypatch.setattr(auth.time, "sleep", lambda *_: None)
    result = auth.notify_auth_complete(
        "http://fixture/api",
        completion_id="completion-1",
        challenge_id="challenge-1",
        scope=scope,
    )
    assert len(calls) == 1
    assert result["request_attempts"] == 1
    assert result["auth_state_confirmed"] is False
    assert not auth._auth_complete_response_confirmed(result, "completion-1")


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("root", "ok", False),
        ("root", "ok", "true"),
        ("root", "auth_state_confirmed", None),
        ("root", "completion_id", "other"),
        ("root", "scope", "seed"),
        ("snapshot", "completion_id", "other"),
        ("snapshot", "expected_challenge_id", "other"),
        ("snapshot", "expected_challenge_id", None),
        ("snapshot", "scope", "seed"),
        ("snapshot", "scope", None),
        ("snapshot", "status", "busy"),
        ("snapshot", "status", "failed"),
        ("snapshot", "status", "completed"),
        ("snapshot", "status", "unknown"),
        ("snapshot", "refreshed", True),
    ],
)
def test_unowned_or_unverified_receipt_keeps_original_retry_budget(
    monkeypatch, section, key, value
):
    calls = []
    response = accepted()
    (response if section == "root" else response["cookie_snapshot"])[key] = value
    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_ATTEMPTS", 3)
    monkeypatch.setattr(
        auth, "post_json", lambda *a, **kw: calls.append(True) or response
    )
    monkeypatch.setattr(auth.time, "sleep", lambda *_: None)
    result = auth.notify_auth_complete(
        "http://fixture/api",
        completion_id="completion-1",
        challenge_id="challenge-1",
        scope="detail",
    )
    assert len(calls) == result["request_attempts"] == 3
    assert not auth._auth_complete_response_confirmed(result, "completion-1")


@pytest.mark.parametrize(
    "completion_id,challenge_id,scope",
    [
        (None, "challenge-1", "detail"),
        ("completion-1", "challenge-1", None),
        ("completion-1", None, "detail"),
    ],
)
def test_legacy_unbound_calls_keep_existing_retry_policy(
    monkeypatch, completion_id, challenge_id, scope
):
    calls = []
    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_ATTEMPTS", 3)
    monkeypatch.setattr(
        auth, "post_json", lambda *a, **kw: calls.append(True) or accepted()
    )
    monkeypatch.setattr(auth.time, "sleep", lambda *_: None)
    result = auth.notify_auth_complete(
        "http://fixture/api",
        completion_id=completion_id,
        challenge_id=challenge_id,
        scope=scope,
    )
    assert len(calls) == result["request_attempts"] == 3


def test_transport_errors_still_use_existing_bounded_retries(monkeypatch):
    calls, waits = [], []

    def fail(*a, **kw):
        calls.append(True)
        raise ConnectionError("synthetic transport failure")

    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_ATTEMPTS", 3)
    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS", 1)
    monkeypatch.setattr(auth, "post_json", fail)
    monkeypatch.setattr(auth.time, "sleep", waits.append)
    result = auth.notify_auth_complete(
        "http://fixture/api",
        completion_id="completion-1",
        challenge_id="challenge-1",
        scope="detail",
    )
    assert len(calls) == result["request_attempts"] == 3
    assert waits == [1, 2]
    assert not auth._auth_complete_response_confirmed(result, "completion-1")


def test_async_completion_uses_fewer_posts_and_avoids_inflated_backoff(monkeypatch):
    class Clock:
        value = 1000.0

        def now(self):
            return self.value

        def sleep(self, seconds):
            self.value += seconds

    clock = Clock()
    calls = []
    saved = []

    def post(*a, **kw):
        calls.append(clock.now())
        response = accepted()
        if clock.now() >= 1007:
            response.update(
                auth_state_confirmed=True,
                scope_paused=False,
                scope_force_unlock_flag_exists=False,
                captcha_solver={"scopes": {"detail": {"paused": False}}},
            )
            response["cookie_snapshot"].update(status="completed", refreshed=True)
        return response

    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_ATTEMPTS", 3)
    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS", 1)
    monkeypatch.setattr(auth.time, "time", clock.now)
    monkeypatch.setattr(auth.time, "sleep", clock.sleep)
    monkeypatch.setattr(auth, "post_json", post)
    monkeypatch.setattr(pending, "notify_auth_complete", auth.notify_auth_complete)
    monkeypatch.setattr(
        pending, "_save_fallback_state", lambda state: saved.append(deepcopy(state))
    )
    monkeypatch.setattr(pending, "_reset_fallback_state", dict)
    monkeypatch.setattr(retry, "AUTH_COMPLETE_RETRY_BASE_SECONDS", 5)
    monkeypatch.setattr(retry, "AUTH_COMPLETE_RETRY_MAX_SECONDS", 60)
    state = {
        "auth_complete_pending": True,
        "auth_completion_id": "completion-1",
        "challenge_id": "challenge-1",
        "last_success_at": 1000,
        "auth_complete_attempts": 0,
        "scope": "detail",
    }
    for _ in range(30):
        result = pending._retry_pending_auth_confirmation(
            "http://fixture/api", state=state
        )
        if result["confirmed"]:
            break
        assert result["pending"] is True
        state = result["state"]
        clock.sleep(5)
    assert result["confirmed"] is True
    assert calls == [1000, 1005, 1015]
    assert clock.now() - 1000 == 15
    assert [state["auth_complete_attempts"] for state in saved] == [1, 2]
