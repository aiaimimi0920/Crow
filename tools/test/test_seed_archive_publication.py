"""New seed state is published only after durable archive replacement."""

import json
from pathlib import Path

import pytest

from src import archive_json_io
from src.collection.adapters import GenericProductAdapter
from src.collection.seed_service import SeedCollectionService


def submit(archive, items, *, db_first=False, path_for=None, before_persist=None):
    seen, pending, persisted, evicted = {}, [], [], []
    state = (seen, pending, persisted, evicted)
    service = SeedCollectionService(adapter=GenericProductAdapter())

    def persist(item, event_type, metadata):
        published = json.loads(
            Path(metadata["source_file"]).read_text(encoding="utf-8")
        )
        assert item in published
        if before_persist is not None:
            before_persist()
        persisted.append((item, event_type, metadata))

    kwargs = {
        "parse_price": float,
        "safe_int": int,
        "prefer_db_task_reads": lambda: db_first,
        "get_seen_entry": seen.get,
        "get_flat_item": lambda _: None,
        "get_data_path": path_for or (lambda _: str(archive)),
        "update_file_global": lambda *_: None,
        "persist_item_to_db": persist,
        "evict_runtime_item": evicted.append,
        "archive_list_payload": lambda *_: None,
        "set_seen": seen.__setitem__,
        "queue_pending": pending.append,
    }
    return lambda: service.submit_batch({"items": items}, **kwargs), state


@pytest.mark.parametrize("db_first", [False, True])
def test_retry_after_db_failure_does_not_duplicate_published_seed(tmp_path, db_first):
    archive = tmp_path / "seed.json"
    archive.write_text('[{"id":"confirmed","evidence":"keep"}]', encoding="utf-8")
    unavailable = True

    def persist():
        if unavailable:
            raise OSError("database unavailable")

    run, state = submit(
        archive,
        [{"id": "new", "title": "candidate"}],
        db_first=db_first,
        before_persist=persist,
    )
    with pytest.raises(OSError, match="database unavailable"):
        run()
    assert state == ({}, [], [], [])
    published = json.loads(archive.read_text(encoding="utf-8"))
    assert len(published) == 2
    published[1]["evidence"] = "retain previously archived enrichment"
    archive.write_text(json.dumps(published), encoding="utf-8")

    unavailable = False
    assert run() == {"status": "ok", "new": 1}
    records = json.loads(archive.read_text(encoding="utf-8"))
    assert records == published
    seen, pending, persisted, evicted = state
    assert len(persisted) == 1
    assert persisted[0][0]["evidence"] == published[1]["evidence"]
    assert pending == ([] if db_first else [published[1]["id"]])
    assert set(seen) == (set() if db_first else {published[1]["id"]})
    assert evicted == ([published[1]["id"]] if db_first else [])


@pytest.mark.parametrize("failure", ["fsync", "replace", "invalid_json"])
@pytest.mark.parametrize("db_first", [False, True])
def test_failed_new_seed_archive_keeps_runtime_and_db_unchanged(
    tmp_path, monkeypatch, failure, db_first
):
    archive = tmp_path / "seed.json"
    original = b'[{"id":"confirmed","evidence":"keep"}]'
    if failure == "invalid_json":
        original = b'[{"unfinished":'
    archive.write_bytes(original)
    run, state = submit(archive, [{"id": "new", "title": "new"}], db_first=db_first)
    if failure != "invalid_json":

        def fail(*_args):
            raise OSError("synthetic publish failure")

        monkeypatch.setattr(archive_json_io.os, failure, fail)
    with pytest.raises((OSError, ValueError)):
        run()
    assert archive.read_bytes() == original
    assert state == ({}, [], [], [])


@pytest.mark.parametrize("db_first", [False, True])
def test_batch_duplicate_is_merged_once_before_publication(tmp_path, db_first):
    archive = tmp_path / "seed.json"
    archive.write_text('[{"id":"confirmed","evidence":"keep"}]', encoding="utf-8")
    run, (seen, pending, persisted, evicted) = submit(
        archive,
        [
            {"id": "new", "title": "first"},
            {"id": "new", "title": "later", "url": "https://example.invalid"},
        ],
        db_first=db_first,
    )
    assert run() == {"status": "ok", "new": 1}
    records = json.loads(archive.read_text(encoding="utf-8"))
    assert records[0] == {"id": "confirmed", "evidence": "keep"}
    assert len(records) == 2
    item = records[1]
    assert item["title"] == "first"
    assert item["url"] == "https://example.invalid"
    assert len(persisted) == 1
    if db_first:
        assert seen == {}
        assert pending == []
        assert evicted == [item["id"]]
    else:
        assert seen[item["id"]]["data"] == item
        assert pending == [item["id"]]
        assert evicted == []


def test_later_partition_failure_only_publishes_completed_partition(
    tmp_path, monkeypatch
):
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    original = b'[{"id":"confirmed"}]'
    second.write_bytes(original)
    run, (seen, pending, persisted, evicted) = submit(
        first,
        [
            {"id": "one", "collected_at": "2026-09-23"},
            {"id": "two", "collected_at": "2026-09-24"},
        ],
        path_for=lambda day: str(first if day == "2026-09-23" else second),
    )
    replace = archive_json_io.os.replace

    def fail_second(source, target):
        if Path(target) == second:
            raise OSError("second partition failed")
        replace(source, target)

    monkeypatch.setattr(archive_json_io.os, "replace", fail_second)
    with pytest.raises(OSError, match="second partition failed"):
        run()
    published = json.loads(first.read_text(encoding="utf-8"))
    assert len(published) == 1
    assert set(seen) == {published[0]["id"]}
    assert pending == [published[0]["id"]]
    assert len(persisted) == 1
    assert evicted == []
    assert second.read_bytes() == original
