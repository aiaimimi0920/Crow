"""Index loading preserves DB-first and offline recovery boundaries."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.collection_index_loader import load_collection_index
from src.collection_runtime_index import CollectionRuntimeIndex


def load(root, collection, repository, counts):
    synced = []
    load_collection_index(
        root,
        collection=collection,
        repository=repository,
        prefer_db_index=lambda: True,
        db_counts_snapshot=counts,
        sync_record=lambda item: synced.append(dict(item)),
        data_path=lambda _: str(root / "db.json"),
        now=lambda: datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    return synced


def test_db_first_leaves_index_empty_for_on_demand_reads(tmp_path):
    collection = CollectionRuntimeIndex()
    collection.set_seen("stale", {"data": {}})
    collection.queue_pending("stale")
    (tmp_path / "item.json").write_text('{"id": "disk"}', encoding="utf-8")

    def forbidden():
        pytest.fail("DB-first bootstrap must not hydrate all records")

    synced = load(
        tmp_path,
        collection,
        SimpleNamespace(enabled=True, iter_flat_items=forbidden),
        lambda: {"db_total_ids": 3, "db_pending_ids": 2},
    )
    assert collection.snapshot() == ({}, ())
    assert synced == []


@pytest.mark.parametrize("counts_fail", [False, True])
def test_db_fallback_merges_disk_and_repository_records(tmp_path, counts_fail):
    collection = CollectionRuntimeIndex()
    archived = tmp_path / "archive" / "2026"
    archived.mkdir(parents=True)
    disk = archived / "items.json"
    disk.write_text(
        json.dumps([{"id": "item", "status": "done", "title": "disk"}]),
        encoding="utf-8",
    )
    (tmp_path / "model_config.json").write_text('{"id": "config"}', encoding="utf-8")
    repository = SimpleNamespace(
        enabled=True,
        iter_flat_items=lambda: [
            {"id": "item", "url": "https://example.invalid/item"},
            {"id": "db-only", "status": "done"},
        ],
    )

    def counts():
        if counts_fail:
            raise OSError("repository unavailable")
        return {"db_total_ids": 0, "db_pending_ids": 0}

    load(tmp_path, collection, repository, counts)
    seen, pending = collection.snapshot()
    assert set(seen) == {"item", "db-only"}
    assert pending == ("item", "db-only")
    assert seen["item"]["file_path"] == str(disk)
    assert seen["item"]["data"] == {
        "id": "item",
        "status": "done",
        "title": "disk",
        "url": "https://example.invalid/item",
    }
    assert seen["db-only"]["file_path"] == str(tmp_path / "db.json")
