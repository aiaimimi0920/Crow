"""Native completion retains dynamic facade bindings and fail-closed validation."""

import pytest

from src.runtime_state import RuntimeState
from src.server_collection_console import AuthCompletion


def test_completion_is_native_and_context_shares_the_bound_method():
    from src import server

    method = server._collection_observer_auth_complete_payload
    assert not hasattr(server, "_CORE_MODULES")
    assert isinstance(method.__self__, AuthCompletion)
    assert server._CONTEXT._collection_observer_auth_complete_payload is method


def test_saved_completion_observes_runtime_and_callback_replacement(monkeypatch):
    from src import server

    complete = server._collection_observer_auth_complete_payload
    for challenge in ("first", "second"):
        runtime = RuntimeState()
        runtime.recovery.set_challenge(challenge, {})
        monkeypatch.setattr(server, "RUNTIME", runtime)
        monkeypatch.setattr(
            server,
            "_captcha_solver_runtime_status",
            lambda value=challenge: {"paused": True, "marker": value},
        )
        result = complete({"source": "pc2_local_solver"})
        assert result["challenge_id"] == challenge
        assert result["captcha_solver"] == {"paused": True, "marker": challenge}
        assert result["auth_state_confirmed"] is False
        assert result["error"] == "completion_id is required for pc2_local_solver"
        assert runtime.recovery.snapshot().challenge_id == challenge


@pytest.mark.parametrize("target", [None, 42, {}])
def test_seed_completion_rejects_malformed_target_before_scheduling(
    monkeypatch, target
):
    from src import server

    complete = server._collection_observer_auth_complete_payload
    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setattr(
        server,
        "_solver_scope_runtime_status",
        lambda _: {
            "challenge_id": "seed-challenge",
            "last_request": {"target_url": "https://sf.taobao.com/list/all.htm"},
        },
    )
    monkeypatch.setattr(
        server,
        "_schedule_auth_cookie_snapshot_refresh",
        lambda *args, **kwargs: pytest.fail("invalid target scheduled cookie refresh"),
    )
    result = complete({"source": "seed_auth_probe", "target_url": target})
    assert result["stale_challenge"] is True
    assert result["auth_state_confirmed"] is False
