"""Synthetic probes exercise callbacks without credentials or network access."""

import json
from unittest.mock import Mock

import pytest

from src import data_fixer_context
from tools.test import test_sparkai_websocket as probe

PRIVATE = "synthetic-private-request-reply-secret"
pytestmark = pytest.mark.security


def test_probe_transports_payload_but_only_prints_progress(monkeypatch, capsys):
    socket = Mock()
    on_message, on_error, on_close, on_open = probe.build_handlers(PRIVATE, PRIVATE)
    monkeypatch.setattr(probe.thread, "start_new_thread", lambda run, args: run(*args))
    on_open(socket)
    assert PRIVATE in socket.send.call_args.args[0]
    on_message(
        socket,
        json.dumps(
            {
                "header": {"code": 0, "status": 2},
                "payload": {"choices": {"text": [{"content": PRIVATE}]}},
            }
        ),
    )
    on_error(socket, OSError(PRIVATE))
    on_close(socket, None, None)
    socket.close.assert_called_once()
    output = capsys.readouterr().out
    assert PRIVATE not in output
    assert "Sending request" in output and "Analysis Finished" in output
    assert "Received response chunk:" in output and "Error kind: io" in output


def test_probe_errors_print_only_validated_code(capsys):
    socket = Mock()
    on_message, *_ = probe.build_handlers(PRIVATE, PRIVATE)
    for code in (11200, PRIVATE):
        on_message(socket, json.dumps({"header": {"code": code, "message": PRIVATE}}))
    output = capsys.readouterr().out
    assert "Error Code: 11200" in output and "Error Code: unknown" in output
    assert PRIVATE not in output
    assert socket.close.call_count == 2


def test_probe_main_never_prints_signed_url(monkeypatch, capsys):
    monkeypatch.setattr(
        probe,
        "load_secrets",
        lambda: {
            "app_id": PRIVATE,
            "api_key": PRIVATE,
            "api_secret": PRIVATE,
            "models": [{"model_id": PRIVATE}],
        },
    )
    signed_url = "wss://unit.test/?authorization=" + PRIVATE
    monkeypatch.setattr(probe.WsParam, "create_url", lambda _: signed_url)
    socket_factory = Mock()
    monkeypatch.setattr(probe.websocket, "WebSocketApp", socket_factory)
    probe.main()
    assert socket_factory.call_args.args[0] == signed_url
    socket_factory.return_value.run_forever.assert_called_once()
    assert capsys.readouterr().out == "Connecting to configured WebSocket endpoint\n"


def test_data_fixer_preserves_response_and_retries_without_raw_logs(
    monkeypatch, caplog
):
    caplog.set_level("INFO")
    config = {
        key: PRIVATE for key in ("name", "app_id", "api_key", "api_secret", "ws_url")
    }
    monkeypatch.setattr(data_fixer_context, "get_model_pool", lambda: [config])
    service = Mock(final_result='```json\n{"ok": true}\n```')
    monkeypatch.setattr(data_fixer_context, "AIService", lambda _: service)
    monkeypatch.setattr(data_fixer_context, "Ws_Param", Mock())
    transport = Mock()
    monkeypatch.setattr(
        data_fixer_context.websocket, "WebSocketApp", lambda *a, **k: transport
    )

    # simple_ai_call clears the result before each transport invocation.
    def run(**kwargs):
        if transport.run_forever.call_count == 1:
            raise OSError(PRIVATE)
        service.final_result = '```json\n{"ok": true}\n```'

    transport.run_forever.side_effect = run
    monkeypatch.setattr("time.sleep", lambda _: None)
    assert data_fixer_context.simple_ai_call(PRIVATE, pool_idx=0) == '{"ok": true}'
    assert transport.run_forever.call_count == 2
    assert "model_slot=1" in caplog.text and "kind=io" in caplog.text
    assert PRIVATE not in caplog.text


def test_data_fixer_exhausted_retries_keep_empty_result(monkeypatch, caplog):
    config = {
        key: PRIVATE for key in ("name", "app_id", "api_key", "api_secret", "ws_url")
    }
    monkeypatch.setattr(data_fixer_context, "get_model_pool", lambda: [config])
    monkeypatch.setattr(
        data_fixer_context, "AIService", Mock(side_effect=ValueError(PRIVATE))
    )
    monkeypatch.setattr("time.sleep", lambda _: None)
    assert data_fixer_context.simple_ai_call(PRIVATE, pool_idx=0, max_retries=2) == ""
    assert "AI_FAIL" in caplog.text and "kind=invalid_data" in caplog.text
    assert PRIVATE not in caplog.text
