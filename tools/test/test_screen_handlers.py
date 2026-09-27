"""Legacy screening keeps input precedence, fallback and job admission behavior."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_native_screen_binding_and_ingest_exit():
    from src import screen_handlers, server

    handler = object.__new__(server.DataHandler)
    assert handler._post_analysis_screen.__self__ is handler
    assert handler._post_analysis_screen.__func__ is server._post_analysis_screen
    for name in ("_run_analysis_screen", "_post_analysis_screen"):
        assert getattr(server, name).__module__ == screen_handlers.__name__
        assert getattr(server._CONTEXT, name) is getattr(server, name)
    assert "server_handler_ingest" in server._NATIVE_MODULES
    assert not hasattr(server, "_HANDLER_MODULES")


@pytest.fixture
def screen(monkeypatch):
    from src import server

    cached = {"data": {"id": "cached", "margin": 0.1, "title": "old"}}
    index = SimpleNamespace(
        get_seen=Mock(
            side_effect=lambda item_id: cached if item_id == "cached" else None
        )
    )
    repository = SimpleNamespace(
        enabled=True, get_flat_item=Mock(return_value={"id": "db", "margin": 0.2})
    )
    values = {
        "_collection_runtime_index": lambda: index,
        "DB_REPOSITORY": repository,
        "AVM_SERVICE": SimpleNamespace(
            predict_by_item_data=Mock(return_value={}), model_version=lambda: "test"
        ),
        "get_effective_alert_threshold": Mock(return_value=0.15),
        "build_avm_result": Mock(
            side_effect=lambda item_id, data: {
                "id": item_id,
                "margin": data.get("margin"),
                "is_malignant_risk": False,
            }
        ),
        "build_alert_blockers": Mock(
            side_effect=lambda **kwargs: (
                []
                if kwargs["margin"] is not None
                and kwargs["margin"] >= kwargs["threshold"]
                else ["low_margin"]
            )
        ),
        "write_avm_alerts": Mock(),
        "summarize_screen_results": Mock(return_value={"summary": True}),
        "_utc_now": lambda: datetime(2026, 9, 26, tzinfo=timezone.utc),
    }
    for name, value in values.items():
        monkeypatch.setattr(server, name, value)
    return server, cached, repository


def test_screen_inline_overrides_cache_db_fallback_and_sort_without_mutation(screen):
    host, cached, repository = screen
    original = deepcopy(cached)
    result = host._run_analysis_screen(
        {"items": ["db", {"id": "cached", "margin": 0.8, "title": "inline"}, ""]}
    )
    assert [item["id"] for item in result["results"]] == ["cached", "db"]
    assert result["alerts_written"] == 2
    assert result["margin_threshold"] == 0.15
    repository.get_flat_item.assert_called_once_with("db")
    inputs = [
        call.args[0] for call in host.AVM_SERVICE.predict_by_item_data.call_args_list
    ]
    assert inputs[1]["title"] == "inline"
    assert inputs[1]["margin"] == 0.8
    assert cached == original
    alerts = host.write_avm_alerts.call_args.args[0]
    assert [item["id"] for item in alerts] == ["cached", "db"]
    assert all(item["created_at"] == "2026-09-26 00:00:00" for item in alerts)


def test_lookup_and_prediction_failures_still_return_non_alerting_result(screen):
    host, _, repository = screen
    repository.get_flat_item.side_effect = OSError("lookup failed")
    host.AVM_SERVICE.predict_by_item_data.side_effect = RuntimeError(
        "prediction failed"
    )
    result = host._run_analysis_screen(
        {"items": ["missing"], "margin_threshold": "invalid"}
    )
    assert result["total"] == 1 and result["alerts_written"] == 0
    assert result["results"][0]["manual_review_recommended"] is False
    assert result["results"][0]["risk_validation"] == {}
    host.write_avm_alerts.assert_called_once_with([])


def test_admitted_job_uses_current_screen_callback_but_copied_payload(monkeypatch):
    from src import server

    payload = {"items": ["cached"], "execution_mode": "async"}
    monkeypatch.setattr(server, "_require_control_plane", lambda handler: True)
    monkeypatch.setattr(server, "_read_json_body", lambda handler: (True, payload))
    monkeypatch.setattr(server, "_read_execution_mode", lambda handler, data: "async")
    handler = SimpleNamespace(_enqueue_collection_job=Mock())
    server._post_analysis_screen(handler)
    call = handler._enqueue_collection_job.call_args
    assert call.args[0] == "avm_screen"
    assert call.args[2] == "AVM_SCREEN_ASYNC_FAILED"
    assert call.kwargs == {"response_extra": {"execution_mode": "async"}}
    replacement = Mock(return_value={"new": True})
    monkeypatch.setattr(server, "_run_analysis_screen", replacement)
    payload["execution_mode"] = "sync"
    assert call.args[1]() == {"new": True}
    replacement.assert_called_once_with({"items": ["cached"]})


def test_screen_denied_before_body_read(monkeypatch):
    from src import server

    monkeypatch.setattr(server, "_require_control_plane", lambda handler: False)
    reader = Mock()
    monkeypatch.setattr(server, "_read_json_body", reader)
    server._post_analysis_screen(SimpleNamespace())
    reader.assert_not_called()
