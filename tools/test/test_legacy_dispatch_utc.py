import json
from datetime import datetime, timezone
from threading import RLock
from types import SimpleNamespace

from src import server
from src.runtime_state import RuntimeState
from tools.test.test_quality_http_guards import WORKER_HEADERS
from tools.test.test_quality_http_guards import (
    api as api,  # noqa: PLC0414 - pytest fixture re-export
)


def test_dispatch_timestamp_normalization_handles_naive_and_aware_values():
    naive = datetime(2026, 9, 22, 12, 0, 0)  # noqa: DTZ001 - legacy naive timestamp regression
    aware = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)

    assert server._as_utc_timestamp(naive) == aware
    assert server._as_utc_timestamp(aware) == aware


def test_legacy_detail_next_task_skips_recent_aware_dispatch(monkeypatch):
    responses = []
    handler = SimpleNamespace(send_json=responses.append)
    monkeypatch.setattr(server, "_read_json_body", lambda _handler: (True, {}))
    monkeypatch.setattr(server, "_prefer_db_task_reads", lambda: False)
    monkeypatch.setattr(server.RUNTIME.collection, "pending_tasks", ["item-1"])
    monkeypatch.setattr(
        server.RUNTIME.collection,
        "seen_ids",
        {"item-1": {"data": {"url": "https://example.test/item-1"}}},
    )
    monkeypatch.setattr(
        server.RUNTIME.collection, "dispatched_tasks", {"item-1": server._utc_now()}
    )
    monkeypatch.setattr(server.RUNTIME.collection, "lock", RLock())

    server._post_detail_next_task(handler)

    assert responses == [{}]


def test_legacy_detail_batch_skips_recent_aware_dispatch(monkeypatch):
    responses = []
    handler = SimpleNamespace(send_json=responses.append)
    monkeypatch.setattr(server, "_read_json_body", lambda _handler: (True, {}))
    monkeypatch.setattr(server, "_prefer_db_task_reads", lambda: False)
    monkeypatch.setattr(
        server, "_collection_scope_effectively_paused", lambda _scope: False
    )
    monkeypatch.setattr(server.RUNTIME.collection, "pending_tasks", ["item-1"])
    monkeypatch.setattr(
        server.RUNTIME.collection,
        "seen_ids",
        {"item-1": {"data": {"url": "https://example.test/item-1"}}},
    )
    monkeypatch.setattr(
        server.RUNTIME.collection, "dispatched_tasks", {"item-1": server._utc_now()}
    )
    monkeypatch.setattr(server.RUNTIME.collection, "lock", RLock())

    server._post_detail_tasks(handler)

    assert responses == [{"tasks": [], "total": 1, "done": 0}]


def test_batch_dispatch_recovers_orphan_pending_ids(api, monkeypatch):
    state = RuntimeState()
    state.collection.seen_ids.update(
        {
            "ready": {"data": {"url": "https://example.invalid/ready"}},
            "done": {"data": {"is_processed": True}},
        }
    )
    state.collection.pending_tasks[:] = ["missing", "done", "ready"]
    monkeypatch.setattr(server, "RUNTIME", state)
    monkeypatch.setattr(server, "_prefer_db_task_reads", lambda: False)
    monkeypatch.setattr(server, "_collection_scope_effectively_paused", lambda _: False)
    status, _, raw = api("POST", "/api/collection/details/tasks", "{}", WORKER_HEADERS)
    assert status == 200
    assert json.loads(raw) == {
        "tasks": [{"id": "ready", "url": "https://example.invalid/ready"}],
        "total": 2,
        "done": 1,
    }
    assert state.collection.pending_tasks == ["ready"]
    assert set(state.collection.dispatched_tasks) == {"ready"}
    status, _, raw = api("POST", "/api/get_tasks", "{}", WORKER_HEADERS)
    assert status == 200
    assert json.loads(raw) == {"tasks": [], "total": 2, "done": 1}
