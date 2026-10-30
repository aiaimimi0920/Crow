"""An unrelated paused scope cannot discard an owned authentication receipt."""

import pytest

from tools import pc2_solver_auth_pending as pending
from tools import pc2_solver_state_store as store

NOW = 1000.0
TARGETS = {
    "seed": "https://sf.taobao.com/list/50025969__2.htm?page=18",
    "detail": "https://sf-item.taobao.com/sf_item/123.htm",
}
BUDGET = {
    "consecutive_failures": 7,
    "slider_attempts": 9,
    "window_started_at": 100.0,
    "slider_next_attempt_at": 200.0,
    "solver_cooldown_until": 300.0,
    "solver_cooldown_reason": "repeated_solver_failures",
    "solver_cooldown_cycles": 2,
}


def receipt(target_scope="detail", **updates):
    state = store._default_fallback_state()
    state.update(
        BUDGET,
        scope=target_scope,
        challenge_id="owned-challenge",
        last_success_at=800.0,
        auth_complete_pending=True,
        auth_completion_id="owned-receipt",
        auth_complete_target_url=TARGETS[target_scope],
        auth_complete_attempts=2,
        auth_complete_next_retry_at=1100.0,
    )
    state.update(updates)
    return state


def status(scope="detail", field="scopes", **local):
    other = "seed" if scope == "detail" else "detail"
    active = {
        "manual_required": True,
        "paused": True,
        "challenge_id": "unrelated-challenge",
    }
    return {
        **active,
        field: {
            other: dict(active),
            scope: {
                "manual_required": False,
                "paused": False,
                "challenge_id": None,
                "last_status": "manual_auth_completed",
                **local,
            },
        },
    }


@pytest.fixture
def setup_pending(monkeypatch):
    monkeypatch.setattr(pending, "AUTH_COMPLETE_PENDING_MAX_SECONDS", 120.0)
    calls = []

    def notify(_api, **request):
        calls.append(request)
        return {"ok": False, "error": "offline fixture", "request_attempts": 1}

    monkeypatch.setattr(pending, "notify_auth_complete", notify)
    return calls


def retry(monkeypatch, state, latest):
    store._save_fallback_state(state)
    monkeypatch.setattr(pending, "read_solver_status", lambda _api: latest)
    return pending._retry_pending_auth_confirmation("https://nas.test/api", now=NOW)


@pytest.mark.parametrize("scope", ["detail", "seed"])
@pytest.mark.parametrize("field", ["scopes", "collection_scopes"])
@pytest.mark.parametrize("local_pending", [False, True])
def test_other_scope_cannot_expire_receipt(
    monkeypatch, setup_pending, scope, field, local_pending
):
    state = receipt(scope)
    local = {"challenge_id": "owned-challenge"} if local_pending else {}

    result = retry(monkeypatch, state, status(scope, field, **local))

    assert result["pending"] is True
    assert result["confirmed"] is False
    assert result["attempted"] is False
    assert not result.get("superseded")
    assert store._load_fallback_state() == state
    assert setup_pending == []


@pytest.mark.parametrize("scope", ["detail", "seed"])
@pytest.mark.parametrize("challenge_id", ["owned-challenge", "next-generation"])
def test_own_active_scope_still_expires_after_budget(
    monkeypatch, setup_pending, scope, challenge_id
):
    state = receipt(scope)
    latest = status(scope, manual_required=True, paused=True, challenge_id=challenge_id)
    # The local scope, not the legacy aggregate, owns the timeout decision.
    latest.update(manual_required=False, paused=False)

    result = retry(monkeypatch, state, latest)

    assert result["pending"] is False
    assert result["confirmed"] is False
    assert result["superseded"] is True
    assert result["reason"] == "active_challenge_after_auth_confirmation_timeout"
    persisted = store._load_fallback_state()
    assert persisted["auth_completion_id"] is None
    assert persisted["challenge_id"] == "owned-challenge"
    assert {key: persisted[key] for key in BUDGET} == BUDGET
    assert setup_pending == []


@pytest.mark.parametrize("scopes", [{}, {"seed": {}}, None, "invalid"])
def test_missing_or_malformed_owned_scope_preserves_receipt(
    monkeypatch, setup_pending, scopes
):
    state = receipt()
    latest = {"paused": True, "manual_required": True, "scopes": scopes}

    result = retry(monkeypatch, state, latest)

    assert result["pending"] is True
    assert store._load_fallback_state() == state
    assert setup_pending == []


@pytest.mark.parametrize("scope", ["detail", "seed"])
def test_legacy_receipt_uses_its_target_scope(monkeypatch, setup_pending, scope):
    state = receipt(scope, scope=None)

    result = retry(monkeypatch, state, status(scope))

    assert result["pending"] is True
    assert store._load_fallback_state() == state
    assert setup_pending == []


def test_unbound_legacy_receipt_does_not_guess_from_other_scope(
    monkeypatch, setup_pending
):
    state = receipt(scope=None, auth_complete_target_url=None)

    result = retry(monkeypatch, state, status())

    assert result["pending"] is True
    assert store._load_fallback_state() == state
    assert setup_pending == []


def test_explicit_scope_wins_over_target_hint(monkeypatch, setup_pending):
    state = receipt(auth_complete_target_url=TARGETS["seed"])

    result = retry(monkeypatch, state, status())

    assert result["pending"] is True
    assert store._load_fallback_state() == state
    assert setup_pending == []


def test_legacy_single_scope_active_status_still_expires(monkeypatch, setup_pending):
    state = receipt()

    result = retry(monkeypatch, state, {"paused": True, "manual_required": True})

    assert result["superseded"] is True
    assert result["pending"] is False
    assert setup_pending == []


def test_explicit_other_scope_legacy_status_cannot_expire(monkeypatch, setup_pending):
    state = receipt()
    latest = {"scope": "seed", "paused": True, "manual_required": True}

    result = retry(monkeypatch, state, latest)

    assert result["pending"] is True
    assert store._load_fallback_state() == state
    assert setup_pending == []


@pytest.mark.parametrize(
    "latest", [{"error": "offline"}, None, {"scopes": {}}, status()]
)
def test_due_receipt_still_retries_same_identity_with_existing_backoff(
    monkeypatch, setup_pending, latest
):
    state = receipt(auth_complete_next_retry_at=NOW)

    result = retry(monkeypatch, state, latest)

    assert result["pending"] is True
    assert result["attempted"] is True
    assert result["confirmed"] is False
    assert len(setup_pending) == 1
    assert setup_pending[0] == {
        "source": "pc2_local_solver",
        "completion_id": "owned-receipt",
        "challenge_id": "owned-challenge",
        "scope": "detail",
    }
    persisted = store._load_fallback_state()
    assert persisted["auth_completion_id"] == "owned-receipt"
    assert persisted["auth_complete_attempts"] == 3
    assert persisted["auth_complete_next_retry_at"] > NOW
    assert {key: persisted[key] for key in BUDGET} == BUDGET


@pytest.mark.parametrize("confirmed", [False, True])
def test_other_scope_does_not_prevent_owned_ack_processing(
    monkeypatch, setup_pending, confirmed
):
    state = receipt(auth_complete_next_retry_at=NOW)

    def notify(_api, **request):
        setup_pending.append(request)
        return {
            "ok": True,
            "auth_state_confirmed": confirmed,
            "completion_id": "owned-receipt",
            "scope": "detail",
            "captcha_solver": status(),
            "request_attempts": 1,
        }

    monkeypatch.setattr(pending, "notify_auth_complete", notify)
    result = retry(monkeypatch, state, status())

    assert result["attempted"] is True
    assert result["confirmed"] is confirmed
    assert result["pending"] is not confirmed
    assert len(setup_pending) == 1
    persisted = store._load_fallback_state()
    if not confirmed:
        assert persisted["auth_completion_id"] == "owned-receipt"
        assert {key: persisted[key] for key in BUDGET} == BUDGET
    else:
        assert persisted["auth_completion_id"] is None
