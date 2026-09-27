"""Operator HTTP commands authorize before parsing and preserve error envelopes."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

CASES = [
    (
        "_post_region_reset_links",
        "_collection_observer_reset_region_links_payload",
        "REGION_RESET",
    ),
    ("_post_item_reanalyze", "_collection_observer_reanalysis_payload", "REANALYZE"),
    (
        "_post_item_manual_update",
        "_collection_observer_manual_update_payload",
        "MANUAL_UPDATE",
    ),
    (
        "_post_collection_control",
        "_collection_observer_runtime_control_payload",
        "RUNTIME_CONTROL",
    ),
]


@pytest.fixture(params=CASES)
def command(request, monkeypatch):
    from src import server

    method, dependency, code = request.param
    handler = SimpleNamespace(
        path="/api/collection/control/pause?ignored=resume",
        send_json=Mock(),
        send_error_json=Mock(),
    )
    monkeypatch.setattr(server, "_require_control_plane", lambda handler: True)
    monkeypatch.setattr(server, "_read_json_body", lambda handler: (True, {"id": "x"}))
    return server, method, dependency, code, handler


def test_command_keeps_native_handler_descriptor(command):
    from src import observer_command_handlers

    host, name, _, _, _ = command
    handler = object.__new__(host.DataHandler)
    method = getattr(handler, name)
    assert method.__self__ is handler
    assert method.__func__ is getattr(host, name)
    assert method.__module__ == observer_command_handlers.__name__
    assert getattr(host._CONTEXT, name) is method.__func__


def test_unauthorized_command_does_not_parse_or_mutate(command, monkeypatch):
    host, method, dependency, _, handler = command
    read, callback = Mock(), Mock()
    monkeypatch.setattr(host, "_require_control_plane", lambda handler: False)
    monkeypatch.setattr(host, "_read_json_body", read)
    monkeypatch.setattr(host, dependency, callback)
    getattr(host, method)(handler)
    read.assert_not_called()
    callback.assert_not_called()
    handler.send_json.assert_not_called()


@pytest.mark.parametrize("outcome", ["accepted", "rejected", "exception"])
def test_saved_command_uses_current_callback_and_response_mapping(
    command, monkeypatch, outcome
):
    host, method, dependency, code, handler = command
    saved = getattr(host, method)
    result = {"ok": outcome == "accepted", "reason": "example"}
    callback = Mock(return_value=result)
    if outcome == "exception":
        callback.side_effect = RuntimeError("service failure")
    monkeypatch.setattr(host, dependency, callback)
    saved(handler)
    callback.assert_called_once_with(
        "pause" if code == "RUNTIME_CONTROL" else {"id": "x"}
    )
    if outcome == "accepted":
        handler.send_json.assert_called_once_with(result)
        handler.send_error_json.assert_not_called()
    else:
        response = handler.send_error_json.call_args.kwargs
        assert response["status"] == (500 if outcome == "exception" else 400)
        assert response["code"] == "COLLECTION_OBSERVER_" + code + (
            "_FAILED" if outcome == "exception" else "_REJECTED"
        )
        assert response["details"] == (
            {
                "error": "service failure",
                **({"action": "pause"} if code == "RUNTIME_CONTROL" else {}),
            }
            if outcome == "exception"
            else result
        )
