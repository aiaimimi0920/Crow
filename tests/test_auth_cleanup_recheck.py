"""Native auth cleanup releases only the completed challenge's pause."""

import pytest

from src.runtime_state import RuntimeState


@pytest.fixture
def server(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_remember_solver_auth_completion", lambda _: None)
    return server


def test_completion_without_scope_uses_exact_challenge_id(server):
    ids = {}
    for scope in ("seed", "detail"):
        ids[scope] = server._begin_solver_challenge({"scope": scope, "node_id": "pc2"})
        assert (
            server._mark_solver_manual_required(scope=scope, manual_only=True) is None
        )
    before = server._solver_scope_state_path("seed").read_bytes()
    result = server._finalize_auth_completion_after_cookie_snapshot(
        "detail-completed", expected_challenge_id=ids["detail"], completion_request={}
    )
    assert result["auth_state_confirmed"] is True
    assert server._solver_scope_state_path("seed").read_bytes() == before
    assert server._solver_scope_runtime_status("detail")["paused"] is False


def test_unattributed_legacy_completion_cannot_adopt_unrelated_scope(server):
    server._begin_solver_challenge({"scope": "detail", "node_id": "pc2"})
    assert server._mark_solver_manual_required(scope="detail", manual_only=True) is None
    request = {"node_id": "pc1"}
    assert server._persist_solver_challenge_state("legacy", request) is None
    server.RUNTIME.recovery.set_challenge("legacy", request)
    before = server._solver_scope_state_path("detail").read_bytes()
    result = server._finalize_auth_completion_after_cookie_snapshot(
        "legacy-completed", expected_challenge_id="legacy", completion_request=request
    )
    assert result["auth_state_confirmed"] is False
    assert "matching challenge_id" in result["error"]
    assert server._solver_scope_state_path("detail").read_bytes() == before


@pytest.mark.parametrize("scope", [None, "detail"])
def test_successful_auth_keeps_operator_pause(server, scope):
    request = {"node_id": "pc2"}
    if scope:
        request["scope"] = scope
    challenge = server._begin_solver_challenge(request)
    assert server._mark_solver_manual_required(scope=scope, manual_only=True) is None
    server.RUNTIME.control.set_pause(True, "operator")
    result = server._finalize_auth_completion_after_cookie_snapshot(
        "operator-held", expected_challenge_id=challenge, completion_request=request
    )
    assert result["auth_state_confirmed"] is True
    assert server.RUNTIME.control.snapshot().paused is True
    assert server.RUNTIME.control.snapshot().reason == "operator"


def test_running_is_not_itself_an_authentication_failure(server):
    assert server._auth_state_is_confirmed({"running": True}) is True
    assert (
        server._auth_state_is_confirmed({"running": True, "manual_required": True})
        is False
    )


@pytest.mark.parametrize("scope", [None, "detail"])
def test_receipt_failure_does_not_overwrite_operator_intent(server, monkeypatch, scope):
    request = {"node_id": "pc2"}
    if scope:
        request["scope"] = scope
    challenge = server._begin_solver_challenge(request)
    assert server._mark_solver_manual_required(scope=scope, manual_only=True) is None
    server.RUNTIME.control.set_pause(True, "operator")
    monkeypatch.setattr(
        server, "_remember_auth_completion_confirmation", lambda _: "receipt locked"
    )
    result = server._finalize_auth_completion_after_cookie_snapshot(
        "failed-receipt", expected_challenge_id=challenge, completion_request=request
    )
    assert result["auth_state_confirmed"] is False
    assert "receipt locked" in result["error"]
    assert server.RUNTIME.control.snapshot().paused is True
    assert server.RUNTIME.control.snapshot().reason == "operator"
