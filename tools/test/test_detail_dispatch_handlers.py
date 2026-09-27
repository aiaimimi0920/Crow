"""Detail POST dispatch validation, pause and service failure contracts."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def host(monkeypatch):
    from src import server
    from src.runtime_state import RuntimeState

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setattr(server, "_read_json_body", lambda handler: (True, {}))
    monkeypatch.setattr(server, "_prefer_db_task_reads", lambda: True)
    monkeypatch.setattr(
        server, "_collection_scope_effectively_paused", lambda scope: False
    )
    return server


def test_native_dispatch_methods_keep_handler_binding(host):
    from src import detail_dispatch_handlers

    handler = object.__new__(host.DataHandler)
    for name in (
        "_post_detail_tasks",
        "_post_detail_next_task",
        "_post_detail_next_visit",
    ):
        method = getattr(handler, name)
        assert method.__self__ is handler
        assert method.__func__ is getattr(host, name)
        assert method.__module__ == detail_dispatch_handlers.__name__
        assert getattr(host._CONTEXT, name) is getattr(host, name)


@pytest.mark.parametrize(
    "method",
    ["_post_detail_tasks", "_post_detail_next_task", "_post_detail_next_visit"],
)
def test_rejected_body_never_queries_detail_service(host, monkeypatch, method):
    service = Mock()
    monkeypatch.setattr(host, "_detail_collection_service", service)
    monkeypatch.setattr(host, "_read_json_body", lambda handler: (False, None))
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    getattr(host, method)(handler)
    service.assert_not_called()
    handler.send_json.assert_not_called()
    handler.send_error_json.assert_not_called()


def test_paused_batch_uses_empty_response_before_database_access(host, monkeypatch):
    service = Mock()
    monkeypatch.setattr(host, "_detail_collection_service", service)
    monkeypatch.setattr(
        host, "_collection_scope_effectively_paused", lambda scope: scope == "detail"
    )
    handler = SimpleNamespace(send_json=Mock())
    host._post_detail_tasks(handler)
    handler.send_json.assert_called_once_with({"tasks": []})
    service.assert_not_called()


@pytest.mark.parametrize(
    "method, service_method, code",
    [
        ("_post_detail_tasks", "batch_tasks", "AVM_DETAIL_BATCH_TASKS_FAILED"),
        ("_post_detail_next_task", "next_task", "AVM_DETAIL_NEXT_TASK_FAILED"),
        ("_post_detail_next_visit", "next_visit_task", "AVM_NEXT_VISIT_TASK_FAILED"),
    ],
)
def test_service_failure_has_stable_error_envelope(
    host, monkeypatch, method, service_method, code
):
    service = SimpleNamespace(
        **{service_method: Mock(side_effect=RuntimeError("unavailable"))}
    )
    monkeypatch.setattr(host, "_detail_collection_service", lambda: service)
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    getattr(host, method)(handler)
    handler.send_json.assert_not_called()
    args = handler.send_error_json.call_args.kwargs
    assert args["status"] == 500 and args["code"] == code
    assert args["details"] == {"error": "unavailable"}


def test_saved_batch_reads_current_service_and_publishes_dispatch_callbacks(
    host, monkeypatch
):
    saved = host._post_detail_tasks
    dispatched_at = host._utc_now()

    def batch_tasks(**kwargs):
        assert kwargs["batch_size"] == 300
        assert kwargs["cooldown_seconds"] == host.DISPATCH_COOLDOWN_SECONDS
        kwargs["mark_dispatched"]("x", dispatched_at)
        assert kwargs["get_dispatched"]("x") == dispatched_at
        return {"tasks": [{"id": "x"}], "total": 3, "done": 1, "pending": 2}

    monkeypatch.setattr(
        host,
        "_detail_collection_service",
        lambda: SimpleNamespace(batch_tasks=batch_tasks),
    )
    handler = SimpleNamespace(send_json=Mock())
    saved(handler)
    handler.send_json.assert_called_once_with(
        {"tasks": [{"id": "x"}], "total": 3, "done": 1}
    )
    assert host.RUNTIME.collection.dispatched_tasks == {"x": dispatched_at}


@pytest.mark.parametrize("database", [False, True])
def test_saved_next_visit_passes_current_index_lock_and_callbacks(
    host, monkeypatch, database
):
    saved = host._post_detail_next_visit
    index = host.RUNTIME.collection
    record = {"data": {"id": "x", "url": "https://example.test/item"}}
    index.set_seen("x", record)
    dispatched_at = host._utc_now()
    monkeypatch.setattr(host, "_prefer_db_task_reads", lambda: database)

    def next_visit_task(**kwargs):
        assert kwargs["dispatch_lock"] is index.lock
        assert kwargs["legacy_entries"] == (None if database else [("x", record)])
        assert kwargs["dispatched_tasks"] == {}
        assert kwargs["cooldown_seconds"] == host.DISPATCH_COOLDOWN_SECONDS
        kwargs["mark_dispatched"]("x", dispatched_at)
        assert kwargs["get_dispatched"]("x") == dispatched_at
        kwargs["prune_dispatched"](dispatched_at, host.DISPATCH_COOLDOWN_SECONDS)
        return {"task_type": "visit", "id": "x"}

    monkeypatch.setattr(
        host,
        "_detail_collection_service",
        lambda: SimpleNamespace(next_visit_task=next_visit_task),
    )
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    saved(handler)
    handler.send_json.assert_called_once_with({"task_type": "visit", "id": "x"})
    handler.send_error_json.assert_not_called()
    assert index.dispatched_tasks == {"x": dispatched_at}


def test_next_visit_snapshot_failure_is_outside_service_error_boundary(
    host, monkeypatch
):
    snapshot = Mock(side_effect=RuntimeError("snapshot failed"))
    monkeypatch.setattr(
        host,
        "_collection_runtime_index",
        lambda: SimpleNamespace(state_snapshot=snapshot),
    )
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    with pytest.raises(RuntimeError, match="snapshot failed"):
        host._post_detail_next_visit(handler)
    handler.send_error_json.assert_not_called()
