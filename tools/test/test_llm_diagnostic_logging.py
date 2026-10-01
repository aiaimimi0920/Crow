"""LLM console diagnostics never expose configuration or provider payloads."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import check_llm_pool
from src import llm_model_selector, llm_websocket, server_auto_tuning
from src.llm_diagnostics import diagnostic_number, failure_kind, model_slot

PRIVATE = "synthetic-private-token\nFORGED LOG"
pytestmark = pytest.mark.security


@pytest.fixture
def selector(monkeypatch, tmp_path):
    pool = [
        {
            "name": PRIVATE,
            "base_name": "Base",
            "app_id": PRIVATE,
            "api_key": PRIVATE,
            "api_secret": PRIVATE,
            "model_id": PRIVATE,
            "ws_url": "wss://unit.test/?token=" + PRIVATE,
            "max_concurrent": 5,
        }
    ]
    selector = llm_model_selector.ModelSelector(pool)
    monkeypatch.setattr(
        llm_model_selector, "CONFIG_FILE", str(tmp_path / "config.json")
    )
    monkeypatch.setattr(llm_model_selector, "get_model_selector", lambda: selector)
    monkeypatch.setattr(llm_websocket, "get_model_selector", lambda: selector)
    monkeypatch.setattr(llm_websocket, "record_api_metrics", Mock())
    return selector


def test_diagnostic_values_are_bounded_and_never_stringified():
    class Dangerous:
        def __str__(self):
            raise AssertionError("must never stringify arbitrary diagnostic values")

    for value in (PRIVATE, Dangerous(), True, None, -1, 10**100):
        assert diagnostic_number(value) == "unknown"
    assert diagnostic_number(11200) == 11200
    assert model_slot([{"name": PRIVATE}], PRIVATE) == 1
    assert model_slot([], PRIVATE) == "unknown"
    assert failure_kind(TimeoutError(PRIVATE)) == "timeout"
    assert failure_kind(ValueError(PRIVATE)) == "invalid_data"
    assert failure_kind(PRIVATE) == "error"


def test_selector_diagnostics_preserve_limits_and_disabled_state(selector, caplog):
    caplog.set_level(logging.DEBUG)
    assert selector.update_limit(PRIVATE, 7)
    selector.disable_model(PRIVATE, "provider error: " + PRIVATE)
    assert selector.limits[PRIVATE] == 7
    assert selector.disabled_models[PRIVATE] == "provider error: " + PRIVATE
    assert "model_slot=1" in caplog.text and "limit=5 -> 7" in caplog.text
    assert PRIVATE not in caplog.text


def test_selector_save_failure_omits_path_and_exception(selector, monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise OSError(PRIVATE)

    monkeypatch.setattr(llm_model_selector, "open", fail, raising=False)
    selector.save_config()
    assert "Save failed kind=io" in caplog.text
    assert PRIVATE not in caplog.text


@pytest.mark.parametrize("route", ["any", "explicit", "community_search"])
@pytest.mark.parametrize("code", [0, 10013, 11200])
def test_websocket_keeps_results_stats_and_release_without_payload_logs(
    selector, monkeypatch, caplog, route, code
):
    caplog.set_level(logging.DEBUG)
    sockets = []

    class FakeSocket:
        def __init__(self, url, **handlers):
            assert url == "wss://unit.test/?authorization=" + PRIVATE
            self.handlers, self.closed = handlers, False
            sockets.append(self)

        def run_forever(self, **kwargs):
            self.handlers["on_error"](self, OSError(PRIVATE))
            self.handlers["on_message"](
                self,
                json.dumps(
                    {
                        "header": {"code": code, "message": PRIVATE, "status": 2},
                        "payload": {"choices": {"text": [{"content": PRIVATE}]}},
                    }
                ),
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        llm_websocket.Ws_Param,
        "create_url",
        lambda _: "wss://unit.test/?authorization=" + PRIVATE,
    )
    monkeypatch.setattr(llm_websocket.websocket, "WebSocketApp", FakeSocket)
    service = llm_websocket.AIService(selector.pool[0] if route == "explicit" else None)
    result = service.get_response(
        PRIVATE, task_type=route if route == "community_search" else None
    )
    assert result == (PRIVATE if code == 0 else "")
    assert service.error_code == code and sockets[0].closed
    assert selector.active_counts[PRIVATE] == 0
    assert selector.stats[PRIVATE]["success" if code == 0 else "error"] == 1
    assert selector.limits[PRIVATE] == (4 if code == 10013 else 5)
    if code == 11200:
        assert selector.disabled_models[PRIVATE] == "error_code=11200"
    assert "Released model_slot=1" in caplog.text
    assert PRIVATE not in caplog.text


def test_websocket_releases_capacity_on_transport_exception(
    selector, monkeypatch, caplog
):
    def fail(*args, **kwargs):
        raise OSError(PRIVATE)

    monkeypatch.setattr(llm_websocket.Ws_Param, "create_url", fail)
    with pytest.raises(OSError):
        llm_websocket.AIService().get_response(PRIVATE)
    assert selector.active_counts[PRIVATE] == 0
    assert PRIVATE not in caplog.text


def test_websocket_provider_code_does_not_echo_untrusted_string(caplog):
    service = llm_websocket.AIService({"name": PRIVATE})
    socket = Mock()
    service.on_message(
        socket, json.dumps({"header": {"code": PRIVATE, "message": PRIVATE}})
    )
    assert service.error_msg == PRIVATE
    socket.close.assert_called_once()
    assert "code=unknown" in caplog.text and PRIVATE not in caplog.text


def test_pool_cli_is_import_safe_and_reports_slot_capacity(
    selector, monkeypatch, capsys
):
    monkeypatch.setattr(check_llm_pool, "get_model_selector", lambda: selector)
    assert check_llm_pool.main() == 0
    output = capsys.readouterr().out
    assert "Total Models: 1" in output and "Model slot 1 (Limit: 5)" in output
    assert PRIVATE not in output


def test_pool_cli_failure_uses_fixed_category(monkeypatch, capsys):
    def fail():
        raise ValueError(PRIVATE)

    monkeypatch.setattr(check_llm_pool, "get_model_selector", fail)
    assert check_llm_pool.main() == 1
    assert capsys.readouterr().out == "Pool unavailable: invalid_data\n"


@pytest.mark.parametrize("rate,initial,expected", [(0, 5, 7), (10, 5, 3), (2, 5, 5)])
def test_auto_tuner_retains_tuning_and_safe_final_config(
    selector, monkeypatch, caplog, rate, initial, expected
):
    caplog.set_level(logging.INFO)
    selector.limits[PRIVATE] = initial
    monkeypatch.setattr(
        selector,
        "get_stats",
        lambda: {
            PRIVATE: {"success": 100 - rate, "error": rate, "concurrency_error": rate}
        },
    )
    waits = iter([False, False, True] if rate == 2 else [False, True])
    stop = SimpleNamespace(is_set=lambda: False, wait=lambda _: next(waits))
    server_auto_tuning.auto_tuner_thread(stop)
    assert selector.limits[PRIVATE] == expected
    assert "model_slot=1" in caplog.text and PRIVATE not in caplog.text
    if rate == 2:
        assert "Stable; models=1" in caplog.text and "final_limit=5" in caplog.text


def test_auto_tuner_failure_omits_traceback_and_value(selector, monkeypatch, caplog):
    def fail():
        raise ValueError(PRIVATE)

    monkeypatch.setattr(selector, "get_stats", fail)
    waits = iter([False, True])
    stop = SimpleNamespace(is_set=lambda: False, wait=lambda _: next(waits))
    server_auto_tuning.auto_tuner_thread(stop)
    assert "Error kind=invalid_data" in caplog.text and PRIVATE not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
