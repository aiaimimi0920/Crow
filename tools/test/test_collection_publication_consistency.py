"""Real SQLite and archive publication regressions for seed/detail races."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from src import archive_json_io as io
from src.collection.detail_service import DetailCollectionService
from src.collection.publication import pending_marker
from tools.test.test_seed_publication_recovery import case as _case_fixture


@pytest.fixture
def case(tmp_path):
    yield from _case_fixture.__wrapped__(tmp_path)


def test_seed_recreates_missing_archive_from_committed_detail(case):
    service, repo, runtime, _store, path, options = case
    payload = {"items": [{"id": "one", "title": "seed"}]}
    service.submit_batch(payload, **options)
    item_id = service.adapter.item_id(payload["items"][0])
    stale = runtime.collection.get_seen(item_id)["data"]
    repo.upsert_flat_item(
        {**stale, "title": "detail", "source_title": "detail"}, "detail_saved"
    )
    path.unlink()
    service.submit_batch(payload, **options)
    assert (
        io.read_records(path)[0]["title"]
        == repo.get_flat_item(item_id)["title"]
        == "detail"
    )


def test_seed_nested_and_empty_list_enrichment_matches_database(case):
    service, repo, _runtime, _store, path, options = case
    service.submit_batch(
        {
            "items": [
                {
                    "id": "one",
                    "title": "seed",
                    "extra": {"a": "old", "b": None},
                    "links": [],
                }
            ]
        },
        **options,
    )
    service.submit_batch(
        {
            "items": [
                {
                    "id": "one",
                    "title": "new",
                    "extra": {"a": "new", "b": "filled"},
                    "links": ["url"],
                }
            ]
        },
        **options,
    )
    item_id = service.adapter.item_id({"id": "one"})
    db = repo.get_flat_item(item_id)
    archive = io.read_records(path)[0]
    assert db["extra"] == archive["extra"] == {"a": "old", "b": "filled"}
    assert db["links"] == archive["links"] == ["url"]
    assert db["title"] == archive["title"] == "seed"


def test_delayed_detail_publication_cannot_be_overtaken_by_seed(case):
    service, repo, runtime, store, path, options = case
    payload = {"items": [{"id": "one", "title": "seed"}]}
    service.submit_batch(payload, **options)
    item_id = service.adapter.item_id(payload["items"][0])
    detail = {
        **runtime.collection.get_seen(item_id)["data"],
        "title": "detail",
        "source_title": "detail",
    }
    committed, release, attempted = Event(), Event(), Event()

    def delayed_publish(*args):
        committed.set()
        assert release.wait(5)
        return store.update_item_in_json(*args)

    def seed():
        attempted.set()
        return service.submit_batch(payload, **options)

    with ThreadPoolExecutor(max_workers=2) as pool:
        detail_service = DetailCollectionService(
            path.parent, repository=repo, adapter=service.adapter
        )
        detail_result = pool.submit(
            detail_service.apply_working_item_patch,
            item_id=item_id,
            patch_data=detail,
            event_type="detail_saved",
            get_working_item=lambda *_: {
                "data": dict(detail),
                "file_path": str(path),
                "cached": False,
            },
            apply_flat_override_patch=lambda data, patch: data.update(patch),
            reset_structured_sections_for_resync=lambda _: None,
            update_file_global=delayed_publish,
            persist_item_to_db=repo.upsert_flat_item,
            evict_runtime_item=lambda _: None,
            prefer_db_task_reads=lambda: True,
            remove_pending=lambda _: None,
        )
        try:
            assert committed.wait(5)
            seed_result = pool.submit(seed)
            assert attempted.wait(5)
            assert not seed_result.done()
        finally:
            release.set()
        detail_result.result(timeout=5)
        seed_result.result(timeout=5)
    assert (
        io.read_records(path)[0]["title"]
        == repo.get_flat_item(item_id)["title"]
        == "detail"
    )


def test_failed_detail_database_blocks_seed_until_detail_retry(case):
    service, repo, runtime, store, path, options = case
    payload = {"items": [{"id": "one", "title": "seed"}]}
    service.submit_batch(payload, **options)
    item_id = service.adapter.item_id(payload["items"][0])
    detail = {
        **runtime.collection.get_seen(item_id)["data"],
        "title": "detail",
        "source_title": "detail",
    }
    detail_service = DetailCollectionService(
        path.parent, repository=repo, adapter=service.adapter
    )
    args = {
        "item_id": item_id,
        "patch_data": detail,
        "event_type": "detail_saved",
        "get_working_item": lambda *_: {
            "data": dict(detail),
            "file_path": str(path),
            "cached": False,
        },
        "apply_flat_override_patch": lambda data, patch: data.update(patch),
        "reset_structured_sections_for_resync": lambda _: None,
        "update_file_global": store.update_file_global,
        "evict_runtime_item": lambda _: None,
        "prefer_db_task_reads": lambda: True,
        "remove_pending": lambda _: None,
    }

    def fail(*_args, **_kwargs):
        raise OSError("synthetic database outage")

    with pytest.raises(OSError):
        detail_service.apply_working_item_patch(**args, persist_item_to_db=fail)
    assert pending_marker(str(path), item_id).exists()
    assert io.read_records(path)[0]["title"] == "detail"
    assert repo.get_flat_item(item_id)["title"] == "seed"
    with pytest.raises(RuntimeError, match="awaits database recovery"):
        service.submit_batch(payload, **options)
    assert io.read_records(path)[0]["title"] == "detail"
    detail_service.apply_working_item_patch(
        **args, persist_item_to_db=repo.upsert_flat_item
    )
    assert not pending_marker(str(path), item_id).exists()
    service.submit_batch(payload, **options)
    assert (
        io.read_records(path)[0]["title"]
        == repo.get_flat_item(item_id)["title"]
        == "detail"
    )
