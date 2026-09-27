"""Recovery transition validation precedes coordinator mutation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def route(monkeypatch):
    from src import server

    handler = SimpleNamespace(
        path="/api/collection/auth/recovery/claim",
        headers={},
        send_json=Mock(),
        send_error_json=Mock(),
    )
    coordinator = Mock()
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", coordinator)
    monkeypatch.setattr(
        server, "_nas_auth_recovery_authorized", lambda headers: (True, None)
    )

    def invoke(path, payload):
        handler.path = "/api/collection/auth/recovery/" + path
        monkeypatch.setattr(server, "_read_json_body", lambda handler: (True, payload))
        server._post_auth_recovery_transition(handler)

    return server, handler, coordinator, invoke


def test_transition_is_native_handler_function(route):
    from src import auth_recovery_transition_handler

    host, _, _, _ = route
    handler = object.__new__(host.DataHandler)
    method = handler._post_auth_recovery_transition
    assert method.__self__ is handler
    assert method.__func__ is host._post_auth_recovery_transition
    assert method.__module__ == auth_recovery_transition_handler.__name__
    assert host._CONTEXT._post_auth_recovery_transition is method.__func__


def test_restarting_uses_current_coordinator_and_trimmed_id(route, monkeypatch):
    host, handler, _, invoke = route
    replacement = Mock()
    replacement.pc2_restarting.return_value = {"ok": True, "stage": "restarting"}
    monkeypatch.setattr(host, "NAS_AUTH_RECOVERY", replacement)
    invoke("pc2_restarting", {"recovery_id": " rid "})
    replacement.pc2_restarting.assert_called_once_with("rid")
    handler.send_json.assert_called_once_with({"ok": True, "stage": "restarting"})


def test_authentication_precedes_body_parsing(route, monkeypatch):
    host, handler, coordinator, _invoke = route
    read = Mock(side_effect=AssertionError("must not parse unauthorized body"))
    monkeypatch.setattr(host, "_read_json_body", read)
    monkeypatch.setattr(
        host, "_nas_auth_recovery_authorized", lambda headers: (False, "denied")
    )
    host._post_auth_recovery_transition(handler)
    read.assert_not_called()
    assert coordinator.mock_calls == []
    assert handler.send_error_json.call_args.kwargs["status"] == 403


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"protocol_version": "2", "node_id": "pc2"},
        {"protocol_version": 2, "node_id": "PC2"},
    ],
)
def test_heartbeat_rejects_wrong_protocol_without_mutation(route, payload):
    _, handler, coordinator, invoke = route
    invoke("heartbeat", payload)
    assert coordinator.mock_calls == []
    assert handler.send_error_json.call_args.kwargs["status"] == 400


def test_heartbeat_requires_no_recovery_id(route):
    _, handler, coordinator, invoke = route
    invoke("heartbeat?status=ok", {"protocol_version": 2, "node_id": "pc2"})
    coordinator.register_stage_auth_pc2.assert_called_once_with()
    handler.send_json.assert_called_once_with({"ok": True})


@pytest.mark.parametrize(
    "path", ["claim", "snapshot_ready", "pc2_restarting", "result"]
)
def test_missing_recovery_id_prevents_transition(route, path):
    _, handler, coordinator, invoke = route
    invoke(path, {"recovery_id": " "})
    assert coordinator.mock_calls == []
    assert (
        handler.send_error_json.call_args.kwargs["details"]["error"]
        == "recovery_id is required"
    )


def test_claim_normalizes_identity_and_preserves_stale_response(route):
    _, handler, coordinator, invoke = route
    result = {"ok": False, "stale_recovery": True}
    coordinator.claim.return_value = result
    invoke("claim", {"recovery_id": " rid ", "role": " PC1 ", "node_id": "Pc1"})
    coordinator.claim.assert_called_once_with("pc1", "rid", "pc1")
    response = handler.send_error_json.call_args.kwargs
    assert response["status"] == 409 and response["details"] is result


def test_snapshot_converts_parameters_and_handles_invalid_numbers(route):
    _, handler, coordinator, invoke = route
    coordinator.snapshot_ready.return_value = {"ok": True}
    invoke(
        "snapshot_ready",
        {
            "recovery_id": "r",
            "sha256": "digest",
            "cookie_count": "3",
            "created_at_epoch": "1.5",
        },
    )
    coordinator.snapshot_ready.assert_called_once_with(
        "r", sha256="digest", cookie_count=3, created_at_epoch=1.5
    )
    coordinator.reset_mock()
    invoke("snapshot_ready", {"recovery_id": "r", "cookie_count": "bad"})
    coordinator.snapshot_ready.assert_not_called()
    assert handler.send_error_json.call_args.kwargs["status"] == 400


def test_saved_transition_uses_current_result_callback_and_original_payload(
    route, monkeypatch
):
    host, handler, _, _ = route
    saved = host._post_auth_recovery_transition
    payload = {"recovery_id": " r ", "success": True}
    handler.path = "/api/collection/auth/recovery/result"
    monkeypatch.setattr(host, "_read_json_body", lambda handler: (True, payload))
    callback = Mock(return_value={"ok": True})
    monkeypatch.setattr(host, "_nas_auth_recovery_result", callback)
    saved(handler)
    assert callback.call_args.args[0] is payload
    handler.send_json.assert_called_once_with({"ok": True})
