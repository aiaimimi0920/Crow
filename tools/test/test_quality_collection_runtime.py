"""Collection failures must not hide unavailable storage or discard saved records."""

import io
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import src.server_collection_operations as collection_operations
from src import server, server_data_runtime
from src.collection.adapters import TaobaoJudicialAuctionAdapter
from src.collection.seed_service import SeedCollectionService
from src.runtime_state import RuntimeState


@pytest.mark.parametrize(
    "boundary", ["count_search_tasks", "claim_search_task", "search_task_counts"]
)
def test_database_failure_is_not_reported_as_empty_or_complete(boundary, caplog):
    repository = SimpleNamespace(
        enabled=True,
        count_search_tasks=lambda: 1,
        claim_search_task=lambda *a, **k: None,
    )
    setattr(repository, boundary, Mock(side_effect=OSError("database unavailable")))
    service = SeedCollectionService(
        repository=repository, adapter=TaobaoJudicialAuctionAdapter()
    )
    with pytest.raises(OSError, match="database unavailable"):
        service.counts_snapshot() if boundary == "search_task_counts" else service.next_task(
            "worker"
        )
    assert "failed" in caplog.text.lower()


def test_seed_batch_submission_holds_collection_lock(monkeypatch):
    entered = Event()

    class ObservedLock:
        def __enter__(self):
            entered.set()
            return self

        def __exit__(self, *_exc):
            return False

    runtime = SimpleNamespace(
        lock=ObservedLock(),
        seen_ids={},
        pending_tasks=[],
        set_seen=lambda item_id, entry: runtime.seen_ids.__setitem__(item_id, entry),
        queue_pending=lambda item_id: runtime.pending_tasks.append(item_id) or True,
    )

    class Service:
        def submit_batch(self, *_args, **kwargs):
            assert entered.is_set()
            assert callable(kwargs["set_seen"])
            assert callable(kwargs["queue_pending"])
            return {"status": "ok"}

    monkeypatch.setattr(
        collection_operations, "_collection_runtime_index", lambda: runtime
    )
    monkeypatch.setattr(
        collection_operations, "_seed_collection_service", lambda: Service()
    )
    monkeypatch.setattr(collection_operations, "_prefer_db_task_reads", lambda: False)
    monkeypatch.setattr(
        collection_operations, "DB_REPOSITORY", SimpleNamespace(enabled=False)
    )
    monkeypatch.setattr(
        collection_operations, "get_data_path", lambda *_args: "", raising=False
    )
    monkeypatch.setattr(
        collection_operations, "update_file_global", lambda *_args: None, raising=False
    )
    monkeypatch.setattr(
        collection_operations, "persist_item_to_db", lambda *_args: None, raising=False
    )
    monkeypatch.setattr(
        collection_operations, "_evict_runtime_item", lambda *_args: None, raising=False
    )
    monkeypatch.setattr(
        collection_operations,
        "archive_list_payload",
        lambda *_args: None,
        raising=False,
    )

    assert collection_operations.handle_seed_batch_submission({"items": []}) == {
        "status": "ok"
    }


@pytest.mark.security
@pytest.mark.parametrize("contents", [b'{"partial":', b'{"archived_record": true}'])
def test_seed_batch_does_not_replace_unreadable_existing_archive(tmp_path, contents):
    archive = tmp_path / "archive.json"
    archive.write_bytes(contents)
    adapter = SimpleNamespace(
        item_id=lambda item: item["id"],
        accepts_seed=lambda *_: True,
        build_seed_record=lambda item, **_: dict(item),
        partition_key=lambda _: "date",
    )
    service = SeedCollectionService(adapter=adapter)
    with pytest.raises(ValueError):
        service.submit_batch(
            {"items": [{"id": "new"}]},
            parse_price=float,
            safe_int=int,
            prefer_db_task_reads=lambda: False,
            get_seen_entry=lambda _: None,
            get_flat_item=lambda _: None,
            get_data_path=lambda _: str(archive),
            update_file_global=lambda *_: None,
            persist_item_to_db=lambda *_: None,
            evict_runtime_item=lambda _: None,
            archive_list_payload=lambda *_: None,
            set_seen=lambda *_args: None,
            queue_pending=lambda _item_id: True,
        )
    assert archive.read_bytes() == contents


def test_reload_keeps_the_runtime_containers_held_by_analysis_callbacks(
    tmp_path, monkeypatch
):
    seen, pending = {"old": {}}, ["old"]
    monkeypatch.setattr(server.RUNTIME.collection, "seen_ids", seen)
    monkeypatch.setattr(server.RUNTIME.collection, "pending_tasks", pending)
    monkeypatch.setattr(server, "DB_REPOSITORY", SimpleNamespace(enabled=False))
    server.load_data(tmp_path)
    assert (
        server.RUNTIME.collection.seen_ids is seen
        and server.RUNTIME.collection.pending_tasks is pending
    )
    seen["completed-in-callback"] = {"data": {"is_processed": True}}
    assert server.RUNTIME.collection.seen_ids["completed-in-callback"]["data"][
        "is_processed"
    ]


def test_detail_dispatch_waits_for_concurrent_completion_under_data_lock(monkeypatch):
    seen = {"item": {"data": {"url": "https://example.invalid/item"}}}
    monkeypatch.setattr(server.RUNTIME.collection, "seen_ids", seen)
    monkeypatch.setattr(server.RUNTIME.collection, "pending_tasks", ["item"])
    monkeypatch.setattr(server.RUNTIME.collection, "dispatched_tasks", {})
    monkeypatch.setattr(server, "_prefer_db_task_reads", lambda: False)
    monkeypatch.setattr(server, "_collection_scope_effectively_paused", lambda _: False)
    entered, sent = Event(), Event()
    responses = []
    handler = SimpleNamespace(
        rfile=io.BytesIO(b"{}"),
        headers={"Content-Length": "2", "Content-Type": "application/json"},
        send_json=lambda value: (responses.append(value), sent.set()),
        send_error_json=lambda **kwargs: pytest.fail(
            f"unexpected request error: {kwargs}"
        ),
    )

    def dispatch():
        entered.set()
        server._post_detail_tasks(handler)

    with server.RUNTIME.collection.lock:
        worker = Thread(target=dispatch, daemon=True)
        worker.start()
        assert entered.wait(2)
        assert not sent.wait(0.1)
        seen["item"]["data"]["is_processed"] = True
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert responses == [{"tasks": [], "total": 1, "done": 1}]


@pytest.mark.parametrize("module", [server, server_data_runtime])
def test_reload_uses_the_injected_runtime_without_replacing_its_queue(
    tmp_path, monkeypatch, module
):
    runtime = RuntimeState()
    pending = runtime.collection.pending_tasks
    pending.append("outdated")
    (tmp_path / "archive.json").write_text(
        '[{"id":"fresh","status":"done"}]', encoding="utf-8"
    )
    monkeypatch.setattr(module, "RUNTIME", runtime)
    monkeypatch.setattr(module, "DB_REPOSITORY", SimpleNamespace(enabled=False))
    monkeypatch.setattr(module, "sync_collection_record", lambda _item: None)

    module.load_data(tmp_path)

    assert runtime.collection.pending_tasks is pending
    assert pending == ["fresh"]
    assert runtime.collection.seen_ids["fresh"]["data"]["id"] == "fresh"


def test_detail_dispatch_uses_the_replacement_runtime_queue(monkeypatch):
    runtime = RuntimeState()
    runtime.collection.set_seen(
        "fresh", {"data": {"url": "https://example.test/fresh"}}
    )
    runtime.collection.queue_pending("fresh")
    pending = runtime.collection.pending_tasks
    dispatched = runtime.collection.dispatched_tasks
    monkeypatch.setattr(server, "RUNTIME", runtime)
    monkeypatch.setattr(server, "_read_json_body", lambda _: (True, {}))
    monkeypatch.setattr(server, "_prefer_db_task_reads", lambda: False)
    monkeypatch.setattr(server, "_collection_scope_effectively_paused", lambda _: False)
    responses = []

    server._post_detail_tasks(SimpleNamespace(send_json=responses.append))

    assert responses == [
        {
            "tasks": [{"id": "fresh", "url": "https://example.test/fresh"}],
            "total": 1,
            "done": 0,
        }
    ]
    assert runtime.collection.pending_tasks is pending
    assert runtime.collection.dispatched_tasks is dispatched
    assert set(dispatched) == {"fresh"}
