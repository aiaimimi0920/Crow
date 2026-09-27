"""Nonempty maintenance previews and failures preserve real records and evidence."""

import json
from datetime import datetime

import pytest

from src.collection import detail_archive_fetch, detail_backfill
from src.collection.adapters.taobao_judicial import TaobaoJudicialAuctionAdapter
from src.collection.detail_service import DetailCollectionService
from src.storage import CollectionRepository, DatabaseSettings


@pytest.fixture
def maintenance(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    adapter = TaobaoJudicialAuctionAdapter()
    repo = CollectionRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'records.sqlite3').as_posix()}",
            enabled=True,
            auto_create=True,
        ),
        adapter=adapter,
    )
    date = datetime.now().strftime("%Y-%m-%d")
    evidence = root / "original.html"
    evidence.write_text(
        "<html><script>var center=[121.5001,31.2002];</script>"
        '<div id="J_NoticeDetail">Original evidence</div></html>',
        encoding="utf-8",
    )
    rows = [
        {
            "id": str(i),
            "status": "done",
            "detail_captured": True,
            "auction_date": date,
            "交易时间": date,
            "建筑面积": 80,
            "url": f"https://sf-item.taobao.com/sf_item/{i}.htm",
        }
        for i in (1, 2)
    ]
    rows[0]["detail_archive_path"] = evidence.name
    path = root / f"{date}.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    for row in rows:
        repo.upsert_flat_item(
            row, event_type="seed", event_payload={"source_file": str(path)}
        )
    service = DetailCollectionService(root, repository=repo, adapter=adapter)
    try:
        yield root, path, repo, service
    finally:
        repo.engine.dispose()


def snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


def test_nonempty_dry_run_preserves_files_database_and_avoids_network_ai(
    maintenance, monkeypatch
):
    root, _, repo, service = maintenance
    before_files = snapshot(root)
    before_records = [repo.get_flat_item(str(i)) for i in (1, 2)]

    def forbidden(*_args, **_kwargs):
        pytest.fail("preview called network or paid extraction")

    monkeypatch.setattr(detail_archive_fetch.requests, "Session", forbidden)
    monkeypatch.setattr(
        detail_backfill.llm_helper, "extract_avm_risk_features", forbidden
    )
    report = service.run_maintenance(
        dry_run=True, fetch_archives=True, prepare_replay=True, extract_risk=True
    )
    assert report["detail_archive_fetch"]["candidate_count"] > 0
    assert report["archived_detail_backfill"]["planned_count"] > 0
    assert report["detail_replay_preparation"]["prepared_count"] > 0
    assert report["ai_calls"] == 0
    assert snapshot(root) == before_files
    assert [repo.get_flat_item(str(i)) for i in (1, 2)] == before_records


def test_backfill_limit_publishes_first_batch_and_preserves_existing_evidence(
    maintenance,
):
    root, path, repo, service = maintenance
    original = (root / "original.html").read_bytes()
    report = service.backfill_archived(limit=1, dry_run=False)
    assert report["updated_records"] == report["scanned_archives"] == 1
    row = repo.get_flat_item("1")
    assert row["latitude"] == 31.2002
    assert (root / row["notice_text_path"]).read_text(
        encoding="utf-8"
    ) == "Original evidence"
    assert (root / "original.html").read_bytes() == original
    assert json.loads(path.read_text(encoding="utf-8"))[0]["latitude"] == 31.2002


def test_backfill_db_failure_retains_old_evidence_and_can_retry(
    maintenance, monkeypatch
):
    root, _, repo, service = maintenance
    service.backfill_archived(limit=1, dry_run=False)
    old = repo.get_flat_item("1")
    old_files = snapshot(root / "html_archive")
    # Force an explicit retry candidate with an old, published sidecar reference.
    monkeypatch.setattr(repo, "iter_archived_detail_candidates", lambda **_: [old])
    original_write = repo.upsert_flat_items

    def fail(*_args, **_kwargs):
        raise OSError("isolated DB failure")

    monkeypatch.setattr(repo, "upsert_flat_items", fail)
    # Remove one factual field in JSON, leaving DB and its evidence untouched.
    path = next(root.glob("20*.json"))
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[0].pop("notice_text_path", None)
    path.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(OSError, match="isolated DB"):
        service.backfill_archived(limit=1, dry_run=False)
    assert repo.get_flat_item("1") == old
    assert all(
        (root / "html_archive" / name).read_bytes() == data
        for name, data in old_files.items()
        if data is not None
    )
    monkeypatch.setattr(repo, "upsert_flat_items", original_write)
    # A normal retry publishes the ahead-of-DB JSON without editing its input.
    assert service.backfill_archived(limit=1, dry_run=False)["updated_records"] == 1
    assert (root / repo.get_flat_item("1")["notice_text_path"]).is_file()


def test_replay_db_failure_retries_published_marker(maintenance, monkeypatch):
    _, _, repo, service = maintenance
    original_write = repo.upsert_flat_items

    def fail(*_args, **_kwargs):
        raise OSError("isolated replay DB failure")

    before = repo.get_flat_item("2")
    monkeypatch.setattr(repo, "upsert_flat_items", fail)
    with pytest.raises(OSError, match="replay DB"):
        service.prepare_replay(dry_run=False)
    assert repo.get_flat_item("2") == before
    monkeypatch.setattr(repo, "upsert_flat_items", original_write)
    assert service.prepare_replay(dry_run=False)["prepared_count"] == 1
    assert repo.get_flat_item("2")["detail_replay_requested_at"]
    assert service.prepare_replay(dry_run=False)["prepared_count"] == 0


def test_fetch_db_failure_retries_without_network_or_paid_extraction(
    maintenance, monkeypatch
):
    root, _, repo, service = maintenance
    original_write = repo.upsert_flat_items
    calls = []

    class Session:
        headers = {}

        def get(self, url, **_options):
            calls.append(url)
            from types import SimpleNamespace

            return SimpleNamespace(
                text="<html>" + "evidence " * 40 + "</html>",
                raise_for_status=lambda: None,
            )

    def fail(*_args, **_kwargs):
        raise OSError("isolated fetch DB failure")

    before = repo.get_flat_item("2")
    monkeypatch.setattr(detail_archive_fetch.requests, "Session", Session)
    monkeypatch.setattr(repo, "upsert_flat_items", fail)
    with pytest.raises(OSError, match="fetch DB"):
        service.fetch_missing_archives(dry_run=False)
    assert repo.get_flat_item("2") == before
    files = snapshot(root)
    monkeypatch.setattr(repo, "upsert_flat_items", original_write)
    assert service.fetch_missing_archives(dry_run=False)["fetched_count"] == 1
    assert len(calls) == 1
    assert snapshot(root) == files
    assert (root / repo.get_flat_item("2")["detail_archive_path"]).is_file()
