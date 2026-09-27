"""Archive publication is required before collection state advances."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src import archive_json_io, server_data_runtime
from src.collection.adapters import GenericProductAdapter
from src.collection.detail_service import DetailCollectionService
from src.collection.seed_service import SeedCollectionService
from tools.test.test_quality_http_guards import WORKER_HEADERS
from tools.test.test_quality_http_guards import api as api  # noqa: PLC0414


@pytest.mark.parametrize("facade", [False, True])
def test_disabled_database_keeps_offline_write_contract(monkeypatch, facade):
    from src import server
    from src.storage.repository import DatabaseSettings, PropertyRepository

    repository = PropertyRepository(DatabaseSettings(url="", enabled=False))
    owner = server if facade else server_data_runtime
    monkeypatch.setattr(owner, "DB_REPOSITORY", repository)
    owner.persist_item_to_db({"id": "offline"}, "test")
    owner.mark_item_deleted_in_db("offline", "test")
    assert repository._engine is None


@pytest.mark.parametrize("failure", ["archive", "database"])
def test_http_update_reports_archive_failure_without_consuming_pending(
    api, tmp_path, monkeypatch, failure
):
    from src import server
    from src.runtime_state import RuntimeState

    archive = tmp_path / "archive.json"
    record = {"id": "target", "title": "confirmed"}
    archive.write_text(json.dumps([record]), encoding="utf-8")
    original_bytes = archive.read_bytes()
    state = RuntimeState()
    state.collection.set_seen("target", {"data": record, "file_path": str(archive)})
    state.collection.queue_pending("target")
    service = DetailCollectionService(tmp_path, adapter=GenericProductAdapter())
    monkeypatch.setattr(server, "RUNTIME", state)
    monkeypatch.setattr(server, "_detail_collection_service", lambda: service)
    monkeypatch.setattr(server, "_prefer_db_task_reads", lambda: False)
    monkeypatch.setattr(
        server, "_apply_flat_override_patch", lambda data, patch: data.update(patch)
    )
    monkeypatch.setattr(server, "_reset_structured_sections_for_resync", lambda _: None)

    def fail(*_args, **_kwargs):
        raise OSError("synthetic archive failure")

    if failure == "archive":
        monkeypatch.setattr(archive_json_io.os, "replace", fail)
    else:
        monkeypatch.setattr(
            server, "DB_REPOSITORY", SimpleNamespace(upsert_flat_item=fail)
        )
    status, _, raw = api(
        "POST",
        "/api/collection/details/update_item",
        json.dumps({"id": "target", "title": "unconfirmed"}),
        WORKER_HEADERS,
    )
    assert status == 500
    assert json.loads(raw)["error"]["code"] == "AVM_DETAIL_UPDATE_ITEM_FAILED"
    if failure == "archive":
        assert archive.read_bytes() == original_bytes
    assert record == {"id": "target", "title": "confirmed"}
    assert state.collection.pending_tasks == ["target"]


@pytest.mark.parametrize("action", ["patch", "html", "seed"])
@pytest.mark.parametrize("failure", ["fsync", "replace", "database"])
def test_failed_archive_update_does_not_publish_collection_state(
    tmp_path, monkeypatch, action, failure
):
    adapter = GenericProductAdapter()
    item_id = adapter.item_id({"id": "target"})
    record = {"id": item_id, "nested": {"confirmed": True}}
    confirmed = deepcopy(record)
    archive = tmp_path / "archive.json"
    archive.write_text(json.dumps([record]), encoding="utf-8")
    original_bytes = archive.read_bytes()
    working = {"data": record, "file_path": str(archive), "cached": True}

    def fail(*_args, **_kwargs):
        raise OSError("archive publication failed")

    def forbidden(*_args, **_kwargs):
        pytest.fail("state advanced after archive publication failed")

    def override(data, patch):
        data.update(patch)
        data["nested"]["confirmed"] = False

    if failure == "database":
        monkeypatch.setattr(
            server_data_runtime, "DB_REPOSITORY", SimpleNamespace(upsert_flat_item=fail)
        )
    else:
        monkeypatch.setattr(archive_json_io.os, failure, fail)
    common = {
        "update_file_global": server_data_runtime.update_file_global,
        "persist_item_to_db": server_data_runtime.persist_item_to_db
        if failure == "database"
        else forbidden,
        "evict_runtime_item": forbidden,
        "prefer_db_task_reads": lambda: False,
    }
    detail = {
        **common,
        "item_id": item_id,
        "get_working_item": lambda *_args, **_kwargs: working,
        "apply_flat_override_patch": override,
        "reset_structured_sections_for_resync": lambda _: None,
        "remove_pending": forbidden,
    }
    service = DetailCollectionService(tmp_path, adapter=adapter)
    with pytest.raises(OSError, match="archive publication failed"):
        if action == "patch":
            service.apply_working_item_patch(
                **detail,
                patch_data={"title": "new"},
                event_type="edit",
                mark_processed=True,
            )
        elif action == "html":
            service.submit_html(
                **detail,
                html_content="<html>evidence</html>",
                status="failed_timeout",
                submit_task=forbidden,
            )
        else:
            SeedCollectionService(adapter=adapter).submit_batch(
                {"items": [{"id": "target", "title": "new"}]},
                **common,
                parse_price=float,
                safe_int=int,
                get_seen_entry=lambda _: working,
                get_flat_item=forbidden,
                get_data_path=lambda _: str(archive),
                archive_list_payload=lambda *_: None,
                set_seen=forbidden,
                queue_pending=forbidden,
            )

    assert record == confirmed
    assert working["data"] is record
    if failure != "database":
        assert archive.read_bytes() == original_bytes
        assert len(list(tmp_path.glob("*.tmp"))) == 1
    else:
        assert len(json.loads(archive.read_text(encoding="utf-8"))) == 1
    if action == "html":
        assert not list((tmp_path / "html").glob("item-*.html"))
        snapshots = list((tmp_path / "html").glob(".pending-*.tmp"))
        assert len(snapshots) == 1
        assert snapshots[0].read_text(encoding="utf-8") == "<html>evidence</html>"
