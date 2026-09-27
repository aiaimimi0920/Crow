"""Public LLM helpers use the implementation module's clock and metric state."""

import importlib
import json
from datetime import datetime, timezone

from src import llm_helper, llm_metrics


def test_prediction_log_uses_the_metrics_owner_clock_and_directory(
    tmp_path, monkeypatch
):
    now = datetime(2026, 9, 24, 10, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(llm_metrics, "_utc_now", lambda: now)
    monkeypatch.setattr(llm_metrics, "PREDICTION_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(llm_helper, "PREDICTION_LOG_DIR", str(tmp_path))

    llm_helper.log_prediction_event(
        "test", 12.345, recall_count=2, final_confidence=0.8, item_id=123
    )

    record = json.loads((tmp_path / "2026-09-24.log").read_text(encoding="utf-8"))
    assert record == {
        "timestamp": "2026-09-24T10:30:00+00:00",
        "task_type": "test",
        "item_id": "123",
        "duration_ms": 12.35,
        "recall_count": 2,
        "final_confidence": 0.8,
        "success": True,
        "failure_reason": None,
    }


def test_api_metrics_use_the_owner_state_even_when_facade_alias_is_replaced(
    monkeypatch,
):
    current = {"total": 0, "success": 0, "total_response_time_ms": 0.0}
    stale = {"total": 100, "success": 100, "total_response_time_ms": 100.0}
    monkeypatch.setattr(llm_metrics, "API_METRICS", current)
    monkeypatch.setattr(llm_helper, "API_METRICS", stale)

    llm_helper.record_api_metrics(True, 10)
    llm_helper.record_api_metrics(False, 20)

    assert llm_helper.get_api_metrics() == {
        "total_calls": 2,
        "success_calls": 1,
        "success_rate": 50.0,
        "avg_response_time_ms": 15.0,
    }
    assert stale == {"total": 100, "success": 100, "total_response_time_ms": 100.0}


def test_public_exports_preserve_native_function_and_class_identity():
    for name in (
        "llm_config",
        "llm_metrics",
        "llm_model_selector",
        "llm_websocket",
        "llm_openai_compatible",
        "llm_text_extraction",
        "llm_product_extraction",
        "llm_auction_extraction",
        "llm_avm_risk",
    ):
        owner = importlib.import_module(f"src.{name}")
        for exported in owner.__all__:
            assert getattr(llm_helper, exported) is getattr(owner, exported), exported
