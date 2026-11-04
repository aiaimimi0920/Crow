"""Publication, retry identity and tombstone regressions from the update review."""

import json
import os
from datetime import datetime, timezone

import pytest

from src import archive_json_io
from src.collection.adapters import GenericProductAdapter
from src.collection.archive_records import discover_raw_record_files, publish_records
from src.collection.detail_failures import DetailFailures, input_version
from src.collection.detail_service import DetailCollectionService
from src.collection.seed_service import SeedCollectionService
from src.collection_archive_records import CollectionArchiveRecords
from src.collection_runtime_index import CollectionRuntimeIndex
from src.runtime_state import RuntimeState
from tools.test.test_detail_commit_recovery import EVIDENCE
from tools.test.test_detail_commit_recovery import captured as captured  # noqa: PLC0414


def archive_store():
    state = RuntimeState()
    return CollectionArchiveRecords(
        runtime=lambda: state, exists=os.path.exists, load=archive_json_io.read_records
    )


def test_new_partition_merge_is_discoverable_and_maintenance_wins(tmp_path):
    path = tmp_path / "2026-11-03.json"
    store = archive_store()
    store.update_file_global(path, 2, {"id": 2, "detail": "saved"}, merge=True)
    store.update_file_global(path, "2", {"id": 2, "seed": "new"}, merge=True)
    assert discover_raw_record_files(tmp_path) == [path]
    assert json.loads(path.read_text(encoding="utf-8")) == [
        {"id": 2, "detail": "saved", "seed": "new"}
    ]
    rows = archive_json_io.read_records(path)
    rows[0]["detail"] = "patched"
    repository = type("Disabled", (), {"enabled": False})()
    publish_records(path, rows, rows, repository, "maintenance")
    assert archive_json_io.read_records(path)[0]["detail"] == "patched"


@pytest.mark.parametrize("exhausted", [False, True])
def test_same_html_submission_preserves_version_and_retry_budget(tmp_path, exhausted):
    path = tmp_path / "html" / "item-1.html"
    path.parent.mkdir()
    content = "<html>\n中文 evidence\n</html>"
    path.write_bytes(content.encode("utf-8"))
    failures = DetailFailures(tmp_path)
    version = input_version(path)
    for _ in range(5 if exhausted else 1):
        failures.record("1", version, "extraction", ValueError("synthetic"))
    receipt = failures.path("1").read_bytes()
    service = DetailCollectionService(tmp_path, adapter=GenericProductAdapter())
    submissions = []
    options = {
        "item_id": "1",
        "status": None,
        "get_working_item": lambda *_: {"data": {"id": "1"}, "file_path": "seed.json"},
        "apply_flat_override_patch": lambda *_: None,
        "reset_structured_sections_for_resync": lambda *_: None,
        "update_file_global": lambda *_: None,
        "persist_item_to_db": lambda *_: None,
        "evict_runtime_item": lambda *_: None,
        "prefer_db_task_reads": lambda: False,
        "remove_pending": lambda *_: None,
        "submit_task": lambda name: (
            submissions.append(name) if failures.ready(name) else None
        ),
    }
    service.submit_html(html_content=content, **options)
    assert input_version(path) == version
    assert failures.path("1").read_bytes() == receipt
    assert not failures.ready(str(path))
    assert submissions == []
    service.submit_html(html_content=content + "<!-- changed -->", **options)
    assert failures.ready(str(path))
    assert submissions == [str(path)]
    assert not list(path.parent.glob(".pending-*.tmp"))


def test_partial_seed_failure_is_not_acknowledged_and_replay_recovers(tmp_path):
    adapter = GenericProductAdapter()
    state = CollectionRuntimeIndex()
    store = archive_store()
    path = tmp_path / "2026-11-03.json"
    committed = {}
    fail_bad = True

    def persist(record, *_):
        if fail_bad and record["source_item_id"] == "bad":
            raise OSError("synthetic database failure")
        committed[record["id"]] = record

    service = SeedCollectionService(adapter=adapter)
    options = {
        "parse_price": float,
        "safe_int": int,
        "prefer_db_task_reads": lambda: False,
        "get_seen_entry": state.get_seen,
        "get_flat_item": committed.get,
        "get_data_path": lambda _: str(path),
        "update_file_global": store.update_file_global,
        "persist_item_to_db": persist,
        "evict_runtime_item": lambda *_: None,
        "archive_list_payload": lambda *_: None,
        "set_seen": state.set_seen,
        "queue_pending": state.queue_pending,
    }
    payload = {"items": [{"id": "bad"}, {"id": "good"}]}
    with pytest.raises(RuntimeError, match="1 record\\(s\\) failed"):
        service.submit_batch(payload, **options)
    assert len(committed) == 1
    fail_bad = False
    service.submit_batch(payload, **options)
    assert len(committed) == len(archive_json_io.read_records(path)) == 2


def test_json_tombstone_survives_duplicate_seed_and_claims(tmp_path):
    adapter = GenericProductAdapter()
    index = CollectionRuntimeIndex()
    item_id = adapter.item_id({"id": "rejected"})
    path = tmp_path / "2026-11-03.json"
    store = archive_store()
    tombstone = {"id": item_id, "detail_fetch_status": "detail_rejected"}
    store.update_file_global(path, item_id, tombstone)
    index.set_seen(item_id, {"file_path": str(path), "data": tombstone})
    SeedCollectionService(adapter=adapter).submit_batch(
        {"items": [{"id": "rejected"}]},
        parse_price=float,
        safe_int=int,
        prefer_db_task_reads=lambda: False,
        get_seen_entry=index.get_seen,
        get_flat_item=lambda _: None,
        get_data_path=lambda _: str(path),
        update_file_global=store.update_file_global,
        persist_item_to_db=lambda *_: None,
        evict_runtime_item=lambda *_: pytest.fail("JSON tombstone must remain indexed"),
        archive_list_payload=lambda *_: None,
        set_seen=index.set_seen,
        queue_pending=index.queue_pending,
    )
    assert index.pending_tasks == []
    # 旧进程或启动扫描留下的队列也必须在 claim 边界过滤。
    index.pending_tasks.append(item_id)
    now = datetime.now(timezone.utc)
    assert index.claim_next_pending(now, 60) is None
    index.pending_tasks.append(item_id)
    assert index.claim_pending_batch(now, 60, 10)[0] == []
    assert (
        archive_json_io.read_records(path)[0]["detail_fetch_status"]
        == "detail_rejected"
    )


def test_late_html_cannot_reopen_rejected_detail_without_explicit_replay(captured):
    case = captured
    record = case.repository.get_flat_item(case.item_id)
    record["detail_fetch_status"] = "detail_rejected"
    case.repository.upsert_flat_item(record, "detail_rejected")
    case.app.host.process_single_file(str(case.html))
    assert case.calls == []
    assert case.html.is_file()
    record["detail_replay_requested_at"] = "2026-11-03 00:00:00"
    case.repository.upsert_flat_item(record, "detail_replay_prepared")
    case.app.host.process_single_file(str(case.html))
    assert len(case.calls) == 1
    saved = case.repository.get_flat_item(case.item_id)
    assert saved["detail_fetch_status"] == "captured"
    assert not saved.get("detail_replay_requested_at")
    assert not saved.get("detail_replay_reason")


def test_rejected_explicit_replay_consumes_request_and_remains_terminal(
    captured, monkeypatch
):
    case = captured

    class RejectAdapter(GenericProductAdapter):
        def accepts_detail(self, record):
            return False

    service = DetailCollectionService(
        case.root,
        repository=case.repository,
        adapter=RejectAdapter(source_platform="catalog_x"),
        dispatch_lock=case.app.host.RUNTIME.collection.lock,
    )
    monkeypatch.setattr(case.app.host, "_detail_collection_service", lambda: service)
    record = case.repository.get_flat_item(case.item_id)
    record.update(
        detail_fetch_status="detail_rejected",
        detail_replay_requested_at="2026-11-03 00:00:00",
    )
    case.repository.upsert_flat_item(record, "detail_replay_prepared")
    case.app.host.process_single_file(str(case.html))
    saved = case.repository.get_flat_item(case.item_id)
    assert saved["detail_fetch_status"] == "detail_rejected"
    assert not saved.get("detail_replay_requested_at")
    assert not saved.get("detail_replay_reason")
    case.html.write_text(EVIDENCE, encoding="utf-8")
    case.app.host.process_single_file(str(case.html))
    assert len(case.calls) == 1
