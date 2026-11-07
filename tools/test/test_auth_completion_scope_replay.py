"""Cleared receipts still acknowledge the explicitly requested collection stage."""

import pytest

from src.runtime_state import RuntimeState
from tools.pc2_solver_auth import _auth_complete_response_confirmed


@pytest.fixture
def host(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.delenv("CROW_SOLVER_STATE_DIR", raising=False)
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_collection_runtime_state_label", lambda: "test")
    monkeypatch.setattr(
        server,
        "_auth_cookie_snapshot_runtime_status",
        lambda: {"status": "completed", "refreshed": True},
    )
    return server


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("other_active", [False, True])
def test_confirmed_replay_keeps_scope_when_no_challenge_remains(
    host, scope, other_active
):
    other = "detail" if scope == "seed" else "seed"
    if other_active:
        state = host._new_solver_scope_state()
        state.update(challenge_id="other", paused=True, manual_required=True)
        assert host._persist_solver_scope_state(other, state) is None
    before = host._solver_scope_runtime_status(other)
    assert host._remember_auth_completion_confirmation("completed") is None
    response = host._collection_observer_auth_complete_payload(
        {
            "source": "pc2_local_solver",
            "completion_id": "completed",
            "challenge_id": None,
            "scope": scope,
        }
    )
    assert response["scope"] == scope
    assert response["auth_state_confirmed"] is True and response["idempotent"] is True
    assert _auth_complete_response_confirmed(response, "completed", scope=scope)
    assert host._solver_scope_runtime_status(other) == before


def test_new_same_scope_challenge_cannot_consume_old_confirmation(host):
    assert host._remember_auth_completion_confirmation("completed") is None
    state = host._new_solver_scope_state()
    state.update(challenge_id="new", paused=True, manual_required=True)
    assert host._persist_solver_scope_state("detail", state) is None
    response = host._collection_observer_auth_complete_payload(
        {
            "source": "pc2_local_solver",
            "completion_id": "completed",
            "challenge_id": None,
            "scope": "detail",
        }
    )
    assert response["auth_state_confirmed"] is False
    assert response["stale_challenge"] is True
    assert host._solver_scope_runtime_status("detail")["challenge_id"] == "new"
