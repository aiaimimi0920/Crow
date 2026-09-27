"""Authentication HTTP commands preserve trust checks and stale responses."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

CASES = [
    ("_post_auth_force_reset", "_force_reset_solver_scope", 409),
    ("_post_auth_complete", "_collection_observer_auth_complete_payload", 400),
    (
        "_post_auth_resume_after_cooldown",
        "_collection_observer_resume_after_cooldown_payload",
        400,
    ),
]


@pytest.fixture(params=CASES)
def command(request, monkeypatch):
    from src import server

    name, dependency, rejected_status = request.param
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    payload = {"scope": "detail", "challenge_id": "challenge"}
    monkeypatch.setattr(server, "_require_node_auth", lambda handler: True)
    monkeypatch.setattr(server, "_read_json_body", lambda handler: (True, payload))
    return server, name, dependency, rejected_status, handler, payload


@pytest.mark.parametrize("boundary", ["auth", "body"])
def test_rejected_input_never_calls_command(command, monkeypatch, boundary):
    host, name, dependency, _, handler, payload = command
    read = Mock(return_value=(False, payload))
    callback = Mock()
    monkeypatch.setattr(host, "_read_json_body", read)
    monkeypatch.setattr(host, dependency, callback)
    monkeypatch.setattr(host, "_require_node_auth", lambda handler: boundary != "auth")
    getattr(host, name)(handler)
    assert read.call_count == (0 if boundary == "auth" else 1)
    callback.assert_not_called()
    handler.send_json.assert_not_called()


def test_native_command_descriptor(command):
    from src import auth_command_handlers

    host, name, _, _, _, _ = command
    handler = object.__new__(host.DataHandler)
    method = getattr(handler, name)
    assert method.__self__ is handler
    assert method.__func__ is getattr(host, name)
    assert method.__module__ == auth_command_handlers.__name__
    assert getattr(host._CONTEXT, name) is method.__func__


@pytest.mark.parametrize(
    "result", [{"ok": True}, {"stale_challenge": True}, {"ok": False}]
)
def test_saved_command_uses_current_callback(command, monkeypatch, result):
    host, name, dependency, rejected_status, handler, payload = command
    saved = getattr(host, name)
    callback = Mock(return_value=result)
    monkeypatch.setattr(host, dependency, callback)
    saved(handler)
    if name == "_post_auth_force_reset":
        callback.assert_called_once_with("detail", "challenge")
    else:
        callback.assert_called_once_with(payload)
    if result.get("ok") or result.get("stale_challenge"):
        handler.send_json.assert_called_once_with(result)
        handler.send_error_json.assert_not_called()
    else:
        assert handler.send_error_json.call_args.kwargs["status"] == rejected_status
        assert handler.send_error_json.call_args.kwargs["details"] is result


def test_command_preserves_exception_boundary(command, monkeypatch):
    host, name, dependency, _, handler, _ = command
    monkeypatch.setattr(host, dependency, Mock(side_effect=RuntimeError("failure")))
    if name == "_post_auth_force_reset":
        with pytest.raises(RuntimeError, match="failure"):
            getattr(host, name)(handler)
        handler.send_error_json.assert_not_called()
    else:
        getattr(host, name)(handler)
        response = handler.send_error_json.call_args.kwargs
        assert response["status"] == 500
        assert response["details"] == {"error": "failure"}


@pytest.mark.parametrize("trusted", [False, True])
@pytest.mark.parametrize("target", ["cdp_endpoint", "cookie_snapshot_path"])
def test_completion_checks_current_target_policy(monkeypatch, target, trusted):
    from src import server

    payload = {target: "target"}
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    callback = Mock(return_value={"ok": True})
    policy = Mock(return_value=trusted)
    monkeypatch.setattr(server, "_require_node_auth", lambda handler: True)
    monkeypatch.setattr(server, "_read_json_body", lambda handler: (True, payload))
    monkeypatch.setattr(server, "_collection_observer_auth_complete_payload", callback)
    saved = server._post_auth_complete
    monkeypatch.setattr(
        server,
        "_cdp_endpoint_permitted"
        if target == "cdp_endpoint"
        else "_resolve_auth_cookie_snapshot_path",
        policy,
    )
    saved(handler)
    policy.assert_called_once_with("target" if target == "cdp_endpoint" else payload)
    assert callback.call_count == int(trusted)
    if not trusted:
        assert (
            handler.send_error_json.call_args.kwargs["code"]
            == "COLLECTION_AUTH_TARGET_REJECTED"
        )
