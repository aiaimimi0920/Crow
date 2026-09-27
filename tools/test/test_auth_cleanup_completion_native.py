"""Native auth cleanup respects live generation and validation boundaries."""

import pytest

from src.auth_cleanup_completion import AuthCleanupCompletion
from src.runtime_state import RuntimeState


def test_cleanup_exports_share_native_context_identity():
    from src import server

    for name in AuthCleanupCompletion.__all__:
        method = getattr(server, name)
        assert isinstance(method.__self__, AuthCleanupCompletion)
        assert getattr(server._CONTEXT, name) is method


def test_saved_finalizer_rejects_replaced_challenge_before_cleanup(monkeypatch):
    from src import server

    finalize = server._finalize_auth_completion_after_cookie_snapshot
    monkeypatch.setattr(server, "_challenge_scope_for_request", lambda _: None)
    monkeypatch.setattr(server, "_scope_for_challenge_id", lambda _: None)
    monkeypatch.setattr(
        server,
        "_clear_solver_manual_required_pause_compat",
        lambda *args: pytest.fail("stale snapshot must not clear a pause"),
    )
    for challenge in ("first", "replacement"):
        runtime = RuntimeState()
        runtime.recovery.set_challenge(challenge, {})
        monkeypatch.setattr(server, "RUNTIME", runtime)
        before = runtime.recovery.snapshot()
        result = finalize("receipt", expected_challenge_id="old", completion_request={})
        assert result["stale_challenge"] is True
        assert result["challenge_id"] == challenge
        assert result["auth_state_confirmed"] is False
        assert runtime.recovery.snapshot() == before


def test_saved_cooldown_respects_replaced_challenge_validator(monkeypatch):
    from src import server

    resume = server._collection_observer_resume_after_cooldown_payload
    runtime = RuntimeState()
    runtime.recovery.set_challenge("active", {})
    monkeypatch.setattr(server, "RUNTIME", runtime)
    monkeypatch.setattr(server, "_scope_for_challenge_id", lambda _: None)
    monkeypatch.setattr(server, "_node_auth_challenge_matches", lambda *_: False)
    monkeypatch.setattr(
        server, "_captcha_solver_runtime_status", lambda: {"paused": True}
    )
    monkeypatch.setattr(
        server,
        "_clear_solver_manual_required_pause_compat",
        lambda *args: pytest.fail("rejected cooldown must not clear a pause"),
    )
    result = resume({"resume_request_id": "resume", "challenge_id": "active"})
    assert result["stale_challenge"] is True
    assert result["auth_state_confirmed"] is False
    assert result["challenge_id"] == "active"
    assert runtime.recovery.confirmation_snapshot() == {}
