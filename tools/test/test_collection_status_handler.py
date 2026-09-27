"""Status previews preserve read-only counts, cooldowns and live dependencies."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_native_status_descriptor_and_module_exit():
    from src import collection_status_handler, server

    handler = object.__new__(server.DataHandler)
    assert handler._get_status.__self__ is handler
    assert handler._get_status.__func__ is server._get_status
    assert server._get_status.__module__ == collection_status_handler.__name__
    assert server._CONTEXT._get_status is server._get_status
    assert "server_handler_get_collection" in server._NATIVE_MODULES
    assert not hasattr(server, "_HANDLER_MODULES")


@pytest.fixture
def status(monkeypatch, tmp_path):
    from src import server

    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    seen = {"1": {"data": {"is_processed": True}}, "2": {"data": {}}}
    pending = tuple(str(i) for i in range(1, 120))
    dispatched = {"1": now, "2": now - timedelta(seconds=60)}
    index = SimpleNamespace(
        state_snapshot=Mock(return_value=(seen, pending, dispatched))
    )
    values = {
        "DATA_DIR": tmp_path,
        "DB_REPOSITORY": SimpleNamespace(enabled=False),
        "DISPATCH_COOLDOWN_SECONDS": 60,
        "_collection_runtime_index": Mock(return_value=index),
        "_collection_api_lightweight_status_enabled": Mock(return_value=False),
        "_collection_api_lightweight_status_payload": Mock(
            return_value={"light": True}
        ),
        "_prefer_db_task_reads": Mock(return_value=False),
        "_utc_now": Mock(return_value=now),
        "_as_utc_timestamp": lambda value: value,
        "_db_counts_snapshot": Mock(
            return_value={
                "db_total_ids": 120,
                "db_processed_ids": 3,
                "db_detail_captured_ids": 7,
                "db_pending_ids": 110,
            }
        ),
        "_db_pending_task_candidates": Mock(return_value=[{"id": i} for i in pending]),
        "_seed_collection_service": Mock(
            return_value=SimpleNamespace(
                counts_snapshot=Mock(
                    return_value={"search_pending": 4, "search_done": 5}
                )
            )
        ),
        "llm_helper": SimpleNamespace(get_api_metrics=Mock(return_value={})),
        "AVM_SERVICE": SimpleNamespace(
            data_dir=tmp_path, health_snapshot=Mock(return_value={"health": True})
        ),
        "_avm_operator_eval_summary": Mock(return_value={"summary": True}),
        "_db_collection_stage_snapshot": Mock(return_value={"stage": True}),
        "_db_data_supply_snapshot": Mock(return_value={"supply": True}),
        "_collection_runtime_snapshot": Mock(
            return_value={
                "paused": True,
                "captcha_solver": {},
                "auth_recovery": {},
                "collection_scopes": {},
            }
        ),
    }
    for name, value in values.items():
        monkeypatch.setattr(server, name, value)
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    return server, handler, index, tmp_path


@pytest.mark.parametrize("database", [False, True])
@pytest.mark.parametrize("repository_enabled", [False, True])
def test_status_counts_preview_and_no_mutation(status, database, repository_enabled):
    host, handler, index, root = status
    host._prefer_db_task_reads.return_value = database
    host.DB_REPOSITORY.enabled = repository_enabled
    for filename in (
        "item-1.txt",
        "item-3.html",
        "item-3.txt",
        "item-4.json",
        "other-5.txt",
    ):
        (root / filename).write_text("captured", encoding="utf-8")
    before = deepcopy(index.state_snapshot.return_value)
    host._get_status(handler, None, "/api/status", {})
    payload = handler.send_json.call_args.args[0]
    assert payload["total_ids"] == (120 if database else 2)
    assert payload["captured_count"] == (7 if database else 2)
    assert payload["ai_finalized_count"] == (3 if database else 1)
    assert payload["next_batch_preview"] == [str(i) for i in range(2, 12)]
    assert payload["db_pending_ids"] == (110 if database else None)
    assert payload["data_supply_recent_24h"] == (
        {"supply": True} if repository_enabled else {}
    )
    assert payload["sniff_queue_count"] == 4
    assert payload["sniff_done_count"] == 5
    assert payload["paused"] is True
    assert payload["avm"] == {"health": True, "summary": True}
    assert index.state_snapshot.return_value == before
    handler.send_error_json.assert_not_called()
    if database:
        host._db_pending_task_candidates.assert_called_once_with(limit=100)
    else:
        host._db_pending_task_candidates.assert_not_called()


def test_status_lightweight_shortcut_still_acquires_index(status):
    host, handler, index, _ = status
    host._collection_api_lightweight_status_enabled.return_value = True
    host._get_status(handler, None, "/api/status", {})
    host._collection_runtime_index.assert_called_once_with()
    index.state_snapshot.assert_not_called()
    host._prefer_db_task_reads.assert_not_called()
    host.AVM_SERVICE.health_snapshot.assert_not_called()
    handler.send_json.assert_called_once_with({"light": True})


def test_legacy_status_does_not_preview_beyond_first_hundred(status):
    host, handler, index, _ = status
    seen, pending, _ = index.state_snapshot.return_value
    index.state_snapshot.return_value = (
        seen,
        pending,
        {tid: host._utc_now() for tid in pending[:100]},
    )
    host._get_status(handler, None, "/api/status", {})
    assert handler.send_json.call_args.args[0]["next_batch_preview"] == []


def test_direct_status_binding_uses_injected_module_callbacks(monkeypatch):
    from src import server_handler_get_collection as module

    index = Mock()
    monkeypatch.setattr(
        module, "_collection_runtime_index", lambda: index, raising=False
    )
    monkeypatch.setattr(
        module,
        "_collection_api_lightweight_status_enabled",
        lambda: True,
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "_collection_api_lightweight_status_payload",
        lambda: {"direct": True},
        raising=False,
    )
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    module._get_status(handler, None, "/api/status", {})
    handler.send_json.assert_called_once_with({"direct": True})
    index.state_snapshot.assert_not_called()


def test_status_index_failure_remains_outside_http_boundary(status):
    host, handler, _, _ = status
    host._collection_runtime_index.side_effect = RuntimeError("index failed")
    with pytest.raises(RuntimeError, match="index failed"):
        host._get_status(handler, None, "/api/status", {})
    handler.send_error_json.assert_not_called()


def test_status_saved_handler_uses_replaced_host_callbacks(status, monkeypatch):
    host, handler, _, _ = status
    saved = host._get_status
    monkeypatch.setattr(
        host, "_collection_api_lightweight_status_enabled", lambda: True
    )
    monkeypatch.setattr(
        host, "_collection_api_lightweight_status_payload", lambda: {"new": True}
    )
    saved(handler, None, "/api/status", {})
    handler.send_json.assert_called_once_with({"new": True})


@pytest.mark.parametrize(
    "callback", ["_collection_api_lightweight_status_enabled", "_db_counts_snapshot"]
)
def test_status_payload_failure_maps_to_http_error(status, callback):
    host, handler, _, _ = status
    host._prefer_db_task_reads.return_value = True
    getattr(host, callback).side_effect = RuntimeError("payload failed")
    host._get_status(handler, None, "/api/status", {})
    assert handler.send_error_json.call_args.kwargs == {
        "status": 500,
        "code": "AVM_STATUS_FAILED",
        "message": "状态概览生成失败",
        "details": {"error": "payload failed"},
    }
    handler.send_json.assert_not_called()
