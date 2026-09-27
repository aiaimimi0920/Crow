"""Client diagnostics and unknown POST responses retain wire behavior."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("name", ["_post_client_log", "_server_post_fallback"])
def test_native_diagnostic_adapters(name):
    from src import server, server_handler_compatibility

    handler = object.__new__(server.DataHandler)
    method = getattr(handler, name)
    assert method.__self__ is handler
    assert method.__func__ is getattr(server, name)
    assert method.__module__ == server_handler_compatibility.__name__
    assert getattr(server._CONTEXT, name) is method.__func__


@pytest.mark.parametrize("is_error", [False, True])
def test_client_log_truncates_and_uses_literal_format(monkeypatch, is_error):
    from src import server

    message = "%s " + "x" * 5000
    monkeypatch.setattr(
        server,
        "_read_json_body",
        lambda handler: (True, {"msg": message, "isError": is_error}),
    )
    logger = Mock()
    monkeypatch.setattr(server, "logger", logger)
    handler = SimpleNamespace(send_json=Mock())
    server._post_client_log(handler)
    (logger.error if is_error else logger.info).assert_called_once_with(
        "%s %s", "[Client Error]" if is_error else "[Client Log]", message[:4000]
    )
    (logger.info if is_error else logger.error).assert_not_called()
    handler.send_json.assert_called_once_with({"status": "ok"})


def test_rejected_log_does_not_log_or_respond(monkeypatch):
    from src import server

    monkeypatch.setattr(server, "_read_json_body", lambda handler: (False, {}))
    logger = Mock()
    monkeypatch.setattr(server, "logger", logger)
    handler = SimpleNamespace(send_json=Mock())
    server._post_client_log(handler)
    assert not logger.mock_calls
    handler.send_json.assert_not_called()


@pytest.mark.parametrize("path", ["/api/missing?keep=1", "/ordinary?keep=1", "/api"])
def test_saved_post_fallback_uses_current_guard_and_exact_path(monkeypatch, path):
    from src import server

    saved = server._server_post_fallback
    guard = Mock()
    monkeypatch.setattr(server, "_send_guard_error", guard)
    handler = SimpleNamespace(path=path, send_response=Mock(), end_headers=Mock())
    saved(handler)
    if path.startswith("/api/"):
        guard.assert_called_once_with(
            handler,
            {
                "status": 404,
                "code": "AVM_ENDPOINT_NOT_FOUND",
                "message": "未找到接口",
                "details": {"path": "/api/missing"},
            },
        )
        handler.send_response.assert_not_called()
        handler.end_headers.assert_not_called()
    else:
        guard.assert_not_called()
        handler.send_response.assert_called_once_with(404)
        handler.end_headers.assert_called_once_with()
