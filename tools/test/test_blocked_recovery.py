from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.storage.blocked_recovery import requeue_blocked_items
from src.storage.models import FapaiSeedItem, PropertyAudit, PropertyListing
from src.storage.repository import DatabaseSettings, PropertyRepository


@pytest.fixture
def repository(tmp_path: Path) -> PropertyRepository:
    repo = PropertyRepository(DatabaseSettings(
        url=f"sqlite:///{(tmp_path / 'recovery.sqlite3').as_posix()}",
        echo=False, enable_postgis=False, auto_create=True, enabled=True,
    ))
    repo.initialize()
    return repo


def add_seed(repository: PropertyRepository, status: str, **fields: object) -> None:
    with repository.session_factory.begin() as session:
        session.add(FapaiSeedItem(item_id="123", status=status, **fields))


def recover(repository: PropertyRepository, **options: object) -> dict[str, object]:
    return requeue_blocked_items(repository, ["123"], recovery_id="release-1", **options)[0]


def test_recovery_dry_run_preserves_every_seed_field(repository: PropertyRepository) -> None:
    add_seed(repository, "analysis_blocked", detail_last_error="missing", detail_attempt_count=3)
    assert recover(repository)["target_status"] == "detail_failed"
    with repository.session_factory() as session:
        row = session.get(FapaiSeedItem, "123")
        assert row.status == "analysis_blocked"
        assert row.detail_last_error == "missing"
        assert row.detail_attempt_count == 3
        assert row.source_payload is None


def test_recovery_routes_existing_raw_to_analysis(repository: PropertyRepository, tmp_path: Path) -> None:
    raw = tmp_path / "detail.html"
    raw.write_text("<html>archived evidence</html>", encoding="utf-8")
    add_seed(repository, "analysis_blocked", detail_attempt_count=2, detail_last_error="timeout",
             source_payload={"_analysis_attempt_count": 3, "keep": 7,
                             "_raw_detail_artifacts": {"detail_html_path": str(raw)}})
    result = recover(repository, apply=True)
    assert result["target_status"] == "analysis_failed"
    with repository.session_factory() as session:
        row = session.get(FapaiSeedItem, "123")
        assert row.detail_attempt_count == 2
        assert row.source_payload["keep"] == 7
        assert row.source_payload["_analysis_attempt_count"] == 0
        receipt = row.source_payload["_blocked_recovery"][0]
        assert receipt["analysis_attempts"] == 3
        assert receipt["previous_error"] == "timeout"
    assert raw.read_text(encoding="utf-8") == "<html>archived evidence</html>"


@pytest.mark.parametrize("status", ["analysis_blocked", "detail_blocked"])
def test_missing_raw_recaptures_without_erasing_paths(repository: PropertyRepository, status: str) -> None:
    add_seed(repository, status, detail_attempt_count=3, final_json_path="previous/final.json",
             source_payload={"_raw_detail_artifacts": {"detail_html_path": "missing/raw.html"}})
    assert recover(repository, apply=True)["target_status"] == "detail_failed"
    with repository.session_factory() as session:
        row = session.get(FapaiSeedItem, "123")
        assert row.detail_attempt_count == 0
        assert row.final_json_path == "previous/final.json"
        assert row.source_payload["_raw_detail_artifacts"]["detail_html_path"] == "missing/raw.html"


@pytest.mark.parametrize("status", ["detail_completed", "in_progress", "analysis_in_progress", "pending_detail"])
def test_nonblocked_rows_are_never_requeued(repository: PropertyRepository, status: str) -> None:
    add_seed(repository, status)
    assert recover(repository, apply=True)["skip"] == "not_blocked"


@pytest.mark.parametrize("lease", [None, datetime.now() + timedelta(days=1)])
def test_recovery_protects_active_and_unknown_leases(repository: PropertyRepository, lease: datetime | None) -> None:
    add_seed(repository, "analysis_blocked", detail_leased_by="other", detail_lease_until=lease)
    assert recover(repository, apply=True)["skip"] == "active_or_unknown_lease"


def test_recovery_is_bounded_and_idempotent(repository: PropertyRepository) -> None:
    add_seed(repository, "detail_blocked")
    assert recover(repository, apply=True)["applied"]
    with repository.session_factory.begin() as session:
        session.get(FapaiSeedItem, "123").status = "detail_blocked"
    assert recover(repository, apply=True)["skip"] == "already_recovered"
    result = requeue_blocked_items(repository, ["123"], recovery_id="release-2", apply=True)
    assert result[0]["skip"] == "recovery_limit"


@pytest.mark.parametrize("analysis", [True, False])
def test_claim_does_not_block_another_workers_active_lease(repository: PropertyRepository, analysis: bool) -> None:
    status = "analysis_in_progress" if analysis else "in_progress"
    add_seed(repository, status, detail_leased_by="owner",
             detail_lease_until=datetime.utcnow() + timedelta(seconds=180), detail_attempt_count=3,
             source_payload={"_analysis_attempt_count": 3})
    if analysis:
        assert repository.claim_seed_raw_detail_item("other", max_analysis_attempts=3) is None
    else:
        assert repository.claim_seed_detail_item("other", max_item_attempts=3) is None
    with repository.session_factory() as session:
        row = session.get(FapaiSeedItem, "123")
        assert row.status == status
        assert row.detail_leased_by == "owner"


@pytest.mark.parametrize("version", [None, 1, 3])
def test_normal_upsert_does_not_migrate_existing_formats(repository: PropertyRepository, version: int | None) -> None:
    with repository.session_factory.begin() as session:
        session.add(PropertyListing(item_id="legacy", record_schema_version=version,
                                    canonical_payload={"preserved": True} if version else None))
    repository.upsert_flat_item({"id": "legacy", "title": "Updated"}, event_type="detail_enriched")
    repository.upsert_flat_item({"id": "new", "title": "New"}, event_type="detail_enriched")
    with repository.session_factory() as session:
        legacy = session.get(PropertyListing, "legacy")
        assert legacy.record_schema_version == version
        assert legacy.canonical_payload == ({"preserved": True} if version else None)
        assert session.get(PropertyListing, "new").record_schema_version == 2


@pytest.mark.parametrize("ready", [True, False])
def test_existing_processed_data_is_preserved(repository: PropertyRepository, ready: bool) -> None:
    add_seed(repository, "analysis_blocked", detail_attempt_count=3,
             detail_last_error="old", source_payload={"_analysis_attempt_count": 3})
    with repository.session_factory.begin() as session:
        session.add(PropertyListing(item_id="123", source_title="Keep old facts", area_sqm=72))
        session.add(PropertyAudit(item_id="123", is_processed=True, detail_captured=True,
                                  analysis_ready=ready))
    result = recover(repository, apply=True)
    # Readiness and historical processed flags alone do not prove a final report.
    assert result["skip"] == "processed_requires_review"
    with repository.session_factory() as session:
        assert session.get(PropertyListing, "123").area_sqm == 72
        assert session.get(PropertyListing, "123").record_schema_version is None
        assert session.get(PropertyAudit, "123").is_processed is True
        seed = session.get(FapaiSeedItem, "123")
        assert seed.detail_attempt_count == 3
        assert seed.source_payload["_analysis_attempt_count"] == 3
        assert seed.status == "analysis_blocked"
