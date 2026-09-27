"""Fresh-process storage proof with postprocessing imports denied."""

from __future__ import annotations

import importlib.abc
import sys
from datetime import datetime
from pathlib import Path


class RejectPostprocessing(importlib.abc.MetaPathFinder):
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def find_spec(self, fullname, path=None, target=None):
        if (
            fullname == "src.avm"
            or fullname.startswith(("src.avm.", "tools."))
            or fullname == "tools"
        ):
            self.attempts.append(fullname)
            raise ImportError(f"postprocessing is unavailable: {fullname}")
        return None


def run(data_root: Path, source: str) -> None:
    guard = RejectPostprocessing()
    sys.meta_path.insert(0, guard)
    from sqlalchemy import select

    from src.collection.adapters.generic_product import GenericProductAdapter
    from src.collection.adapters.taobao_judicial import TaobaoJudicialAuctionAdapter
    from src.collection.record_values import safe_float
    from src.storage import CollectionRepository, DatabaseSettings
    from src.storage.models import PropertyAudit, PropertyIngestEvent, PropertyListing

    adapter = (
        TaobaoJudicialAuctionAdapter()
        if source == "taobao_sf"
        else GenericProductAdapter(source_platform=source)
    )
    settings = DatabaseSettings(
        url=f"sqlite:///{(data_root / 'collection.sqlite3').as_posix()}",
        echo=False,
        enable_postgis=False,
        auto_create=True,
        enabled=True,
    )
    repository = CollectionRepository(settings, adapter=adapter)
    url = (
        "https://sf-item.taobao.com/sf_item/123.htm"
        if source == "taobao_sf"
        else "https://catalog.example/items/123"
    )
    job = {
        "job_key": "source-job",
        "location_code": "440115",
        "category": "house",
        "source_url_template": "https://catalog.example/list?page={page}",
    }
    repository.ensure_seed_scan_job(
        job, sort_specs=[{"sort_key": "price", "sort_name": "price", "st_param": "2"}]
    )
    task = repository.claim_seed_scan_page("seed-worker")
    assert task is not None
    seed = {"id": "123", "url": url, "title": "Collected fact", "status": "done"}
    seed_args = dict(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=task["page"],
        source_page_url=task["url"],
        items=[seed],
    )
    if adapter.seed_scan_policy.requires_lease_owner:
        try:
            repository.upsert_seed_items(**seed_args, worker_id="foreign-worker")
        except ValueError:
            pass
        else:
            raise AssertionError("configured source policy must check lease ownership")
    assert (
        repository.upsert_seed_items(**seed_args, worker_id="seed-worker")["new_items"]
        == 1
    )
    assert (
        repository.upsert_seed_items(**seed_args, worker_id="seed-worker")[
            "existing_items"
        ]
        == 1
    )
    claimed = repository.claim_seed_detail_item("detail-worker")
    assert claimed is not None
    item_id = claimed["item_id"]
    assert item_id == adapter.item_id(seed)
    assert claimed["source_item_id"] == "123"
    assert claimed["source_platform"] == source

    record = adapter.build_seed_record(
        seed, parse_number=safe_float, safe_int=safe_float
    )
    record["seller_note"] = "preserve collected extension"
    repository.upsert_flat_item(record, event_type="seed_discovered")
    first = repository.get_flat_item(item_id)
    assert first["source_platform"] == source
    assert first["detail_status"] == "pending"
    assert first["seller_note"] == record["seller_note"]

    archive = data_root / "detail.html"
    archive.write_text("<html>Collected evidence</html>", encoding="utf-8")
    detail_record = {
        "detail_archive_path": str(archive),
        "evidence_span": "Collected evidence",
    }
    adapter.prepare_detail_record(detail_record, existing=record, item_id=item_id)
    record = detail_record
    adapter.finalize_detail_record(record)
    repository.upsert_flat_item(record, event_type="detail_archived")
    repository.mark_seed_detail_completed(item_id)
    detail = repository.get_flat_item(item_id)
    assert detail["detail_status"] == "archived"
    assert detail["is_processed"] is True
    assert Path(detail["detail_archive_path"]).read_text(
        encoding="utf-8"
    ) == archive.read_text(encoding="utf-8")
    assert detail["canonical_payload"]["source"]["id"] == "123"
    assert (
        detail["canonical_payload"]["attributes"]["seller_note"]
        == "preserve collected extension"
    )
    with repository.session_factory() as session:
        events = session.scalars(select(PropertyIngestEvent.event_type)).all()
        assert "detail_stage_transition" in events
        assert not any(event.startswith("analysis_") for event in events)

    # A pre-existing legacy row and its postprocessing metadata are not migrated by a retry.
    scored_at = datetime(2020, 1, 2, 3, 4, 5)
    with repository.session_factory.begin() as session:
        listing = session.get(PropertyListing, item_id)
        listing.record_schema_version = None
        listing.canonical_payload = None
        audit = session.get(PropertyAudit, item_id)
        audit.analysis_status = "not_ready"
        audit.analysis_ready = False
        audit.analysis_missing_fields = ["legacy-review"]
        audit.analysis_model_version = "external-model"
        audit.analysis_last_scored_at = scored_at
    repository.engine.dispose()

    reopened = CollectionRepository(settings, adapter=adapter)
    assert reopened.get_flat_item(item_id)["title"] == "Collected fact"
    reopened.upsert_flat_item(record, event_type="detail_retry")
    with reopened.session_factory() as session:
        listing = session.get(PropertyListing, item_id)
        audit = session.get(PropertyAudit, item_id)
        assert (
            listing.record_schema_version is None and listing.canonical_payload is None
        )
        assert audit.analysis_status == "not_ready" and audit.analysis_ready is False
        assert audit.analysis_missing_fields == ["legacy-review"]
        assert audit.analysis_model_version == "external-model"
        assert audit.analysis_last_scored_at == scored_at
    assert reopened.claim_seed_detail_item("next-worker") is None
    from collection_status_isolation_probe import exercise_status

    exercise_status(reopened, data_root)
    assert not guard.attempts, guard.attempts
    assert not any(
        name == "src.avm" or name.startswith("src.avm.") for name in sys.modules
    )
    reopened.engine.dispose()
    print(f"{source}: seed/detail persisted, legacy retained, postprocessing absent")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    run(Path(sys.argv[1]), sys.argv[2])
