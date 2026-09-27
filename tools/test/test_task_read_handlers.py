"""Task reads retain DB priority, runtime fallback and compatibility routes."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_task_control_exits_cloning_with_native_descriptors():
    from src import server, task_read_handlers

    assert not hasattr(server, "_HANDLER_MODULES")
    handler = object.__new__(server.DataHandler)
    for name in task_read_handlers.TaskReadHandlers.__all__:
        method = getattr(handler, name)
        assert method.__self__ is handler
        assert method.__func__ is getattr(server, name)
        assert method.__module__ == task_read_handlers.__name__
        assert getattr(server._CONTEXT, name) is method.__func__


@pytest.mark.parametrize("database", ["found", "missing", "failed", "disabled"])
@pytest.mark.parametrize("cached", [False, True])
def test_item_read_priority_and_failure_mapping(monkeypatch, database, cached):
    from src import server

    cached_item = {"id": "cached"}
    db_item = {"id": "db"}
    lookup = Mock(return_value=db_item if database == "found" else None)
    if database == "failed":
        lookup.side_effect = RuntimeError("offline")
    index = SimpleNamespace(
        get_seen=Mock(return_value={"data": cached_item} if cached else None)
    )
    saved = server._get_item
    monkeypatch.setattr(server, "_collection_runtime_index", lambda: index)
    monkeypatch.setattr(
        server,
        "DB_REPOSITORY",
        SimpleNamespace(enabled=database != "disabled", get_flat_item=lookup),
    )
    handler = SimpleNamespace(
        path="/api/get_item?id=%20item%20", send_json=Mock(), send_error_json=Mock()
    )
    saved(handler, None, None, {})
    if database != "disabled":
        lookup.assert_called_once_with("item")
    else:
        lookup.assert_not_called()
    if database == "found":
        handler.send_json.assert_called_once_with(db_item)
        index.get_seen.assert_not_called()
    elif cached:
        handler.send_json.assert_called_once_with(cached_item)
    else:
        assert handler.send_error_json.call_args.kwargs["status"] == (
            503 if database == "failed" else 404
        )


@pytest.mark.parametrize(
    "name,callback",
    [
        ("_get_pipeline_status", "status"),
        ("_get_merge_check", "verify_merge_completeness"),
    ],
)
@pytest.mark.parametrize("failed", [False, True])
def test_pipeline_reads_current_owner(monkeypatch, name, callback, failed):
    from src import server

    read = Mock(
        return_value={"ok": True},
        side_effect=RuntimeError("failed") if failed else None,
    )
    saved = getattr(server, name)
    monkeypatch.setattr(server, "AVM_PIPELINE", SimpleNamespace(**{callback: read}))
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    saved(handler, None, None, {})
    read.assert_called_once_with()
    if failed:
        assert handler.send_error_json.call_args.kwargs["status"] == 500
    else:
        handler.send_json.assert_called_once_with({"ok": True})


def test_fallback_and_replay_contracts():
    from src import server

    handler = SimpleNamespace(
        send_response=Mock(),
        end_headers=Mock(),
        send_error_json=Mock(),
        _submit_maintenance_job=Mock(),
    )
    server._get_api_not_found(handler, None, "/api/unknown", {})
    assert handler.send_error_json.call_args.kwargs["details"] == {
        "path": "/api/unknown"
    }
    server._server_get_fallback(handler, None, "/unknown", {})
    handler.send_response.assert_called_once_with(404)
    handler.end_headers.assert_called_once_with()
    server._post_recent_detail_replay(handler)
    handler._submit_maintenance_job.assert_called_once_with(
        "recent_detail_replay", "AVM_RECENT_DETAIL_REPLAY_FAILED"
    )
