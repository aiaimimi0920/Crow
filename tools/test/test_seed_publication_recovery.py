"""Seed retry and concurrent detail evidence use real storage boundaries."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from src import archive_json_io as io
from src.collection.adapters import GenericProductAdapter
from src.collection.seed_service import SeedCollectionService
from src.collection_archive_records import CollectionArchiveRecords
from src.runtime_state import RuntimeState
from src.storage import CollectionRepository, DatabaseSettings


@pytest.fixture
def case(tmp_path):
    adapter = GenericProductAdapter(source_platform="catalog_x")
    repo = CollectionRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'records.sqlite3').as_posix()}",
            enabled=True,
            auto_create=True,
        ),
        adapter=adapter,
    )
    repo.initialize()
    runtime = RuntimeState()
    store = CollectionArchiveRecords(lambda: runtime, os.path.exists, io.read_records)
    path = tmp_path / "records.json"
    options = {
        "parse_price": float,
        "safe_int": int,
        "prefer_db_task_reads": lambda: False,
        "get_seen_entry": runtime.collection.get_seen,
        "get_flat_item": repo.get_flat_item,
        "get_data_path": lambda _: str(path),
        "update_file_global": store.update_file_global,
        "persist_item_to_db": repo.upsert_flat_item,
        "evict_runtime_item": lambda _: None,
        "archive_list_payload": lambda *_: None,
        "set_seen": runtime.collection.set_seen,
        "queue_pending": runtime.collection.queue_pending,
    }
    service = SeedCollectionService(adapter=adapter, repository=repo)
    try:
        yield service, repo, runtime, store, path, options
    finally:
        repo.engine.dispose()


@pytest.mark.parametrize("existing", [False, True])
def test_db_commit_json_failure_is_not_acknowledged_and_replay_repairs(case, existing):
    service, repo, _runtime, _store, path, options = case
    payload = {"items": [{"id": "one", "title": "seed"}]}
    item_id = service.adapter.item_id(payload["items"][0])
    if existing:
        service.submit_batch(payload, **options)
    before = path.read_bytes() if path.exists() else None

    def fail(*args, **kwargs):
        raise OSError("JSON temporarily unavailable")

    with pytest.raises((OSError, RuntimeError)):
        service.submit_batch(payload, **{**options, "update_file_global": fail})
    assert repo.get_flat_item(item_id) is not None
    assert (path.read_bytes() if path.exists() else None) == before
    service.submit_batch(payload, **options)
    assert [row["id"] for row in io.read_records(path)] == [item_id]
    assert io.read_records(path)[0]["title"] == "seed"


def test_late_seed_does_not_replace_committed_detail(case):
    service, repo, runtime, store, path, options = case
    payload = {"items": [{"id": "one", "title": "seed"}]}
    service.submit_batch(payload, **options)
    item_id = service.adapter.item_id(payload["items"][0])
    stale = dict(runtime.collection.get_seen(item_id)["data"])
    detail = {
        **stale,
        "title": "detail",
        "source_title": "detail",
        "is_processed": True,
        "detail_fetch_status": "detail_rejected",
    }
    repo.upsert_flat_item(detail, "detail_rejected")
    assert repo.get_flat_item(item_id)["title"] == "detail"
    store.update_item_in_json(path, item_id, detail)
    # The runtime cache intentionally still contains the old seed snapshot.
    service.submit_batch(payload, **options)
    assert repo.get_flat_item(item_id)["detail_fetch_status"] == "detail_rejected"
    assert repo.get_flat_item(item_id)["title"] == "detail"
    assert io.read_records(path)[0]["title"] == "detail"
    assert runtime.collection.get_seen(item_id)["data"]["title"] == "detail"


def test_two_sqlite_seed_writers_preserve_independent_enrichment(case):
    service, repo, *_ = case
    raw = service.adapter.build_seed_record(
        {"id": "one", "title": "seed"}, parse_number=float, safe_int=int
    )
    repo.upsert_flat_item(raw, "sniff_saved")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(repo.upsert_flat_item, {**raw, key: "evidence"}, "sniff_saved")
            for key in ("extra_a", "extra_b")
        ]
        for future in futures:
            future.result(timeout=10)
    stored = repo.get_flat_item(raw["id"])
    assert stored["extra_a"] == stored["extra_b"] == "evidence"
