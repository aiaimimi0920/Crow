from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.collection.seed_list_parser import normalize_source_item_id
from src.collection.seed_scan_policy import GenericSeedScanPolicy
from src.storage.models import FapaiSeedItem, FapaiSeedOccurrence, PropertyListing
from tools import detail_worker
from tools.test.seed_queue_repository_test_context import _ensure_nansha_job, _make_repo


def _claim_generic_task(repo, policy: GenericSeedScanPolicy, job_key: str):
    repo.ensure_seed_scan_job(
        {
            "job_key": job_key,
            "source_url_template": f"https://{policy.source_platform}.example/list?page={{page}}",
        },
        sort_specs=[{"sort_key": "source", "sort_name": "source", "st_param": ""}],
        policy=policy,
    )
    task = repo.claim_seed_scan_page(f"worker-{policy.source_platform}", policy=policy)
    assert task is not None
    return task


def _upsert_generic(repo, policy: GenericSeedScanPolicy, task, source_item_id: str):
    return repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=task["page"],
        source_page_url=task["url"],
        items=[
            {
                "id": source_item_id,
                "url": f"https://{policy.source_platform}.example/items/{source_item_id}",
            }
        ],
        policy=policy,
        worker_id=f"worker-{policy.source_platform}",
    )


def test_generic_seed_identity_is_scoped_by_source_platform(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    policy_x = GenericSeedScanPolicy(source_platform="catalog_x")
    policy_y = GenericSeedScanPolicy(source_platform="catalog_y")
    task_x = _claim_generic_task(repo, policy_x, "catalog-x")
    task_y = _claim_generic_task(repo, policy_y, "catalog-y")

    assert _upsert_generic(repo, policy_x, task_x, "shared-1")["new_items"] == 1
    duplicate = _upsert_generic(repo, policy_x, task_x, "shared-1")
    assert duplicate["existing_items"] == 1
    assert duplicate["new_occurrences"] == 0
    assert _upsert_generic(repo, policy_y, task_y, "shared-1")["new_items"] == 1

    item_id_x = policy_x.storage_item_id("shared-1")
    item_id_y = policy_y.storage_item_id("shared-1")
    assert item_id_x != item_id_y
    with repo.session_factory() as session:
        rows = session.scalars(select(FapaiSeedItem).order_by(FapaiSeedItem.item_id)).all()
        assert len(rows) == 2
        assert {row.source_item_id for row in rows} == {"shared-1"}
        assert {row.source_platform for row in rows} == {"catalog_x", "catalog_y"}
        assert session.scalar(select(func.count()).select_from(FapaiSeedOccurrence)) == 2

    claimed = [
        repo.claim_seed_detail_item("detail-worker", lease_seconds=30),
        repo.claim_seed_detail_item("detail-worker", lease_seconds=30),
    ]
    assert {item["item_id"] for item in claimed if item} == {item_id_x, item_id_y}
    assert {item["id"] for item in claimed if item} == {"shared-1"}
    assert {item["source_item_id"] for item in claimed if item} == {"shared-1"}
    assert {item["source_platform"] for item in claimed if item} == {"catalog_x", "catalog_y"}

    observer = repo.collection_observer_item_detail(item_id_x)
    assert observer["item"]["source_platform"] == "catalog_x"
    assert observer["item"]["source_item_id"] == "shared-1"


def test_taobao_seed_identity_keeps_legacy_item_id(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    task = repo.claim_seed_scan_page("taobao-worker")
    assert task is not None

    result = repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=task["page"],
        source_page_url=task["url"],
        items=[{"id": "1001", "url": "https://sf-item.taobao.com/sf_item/1001.htm"}],
    )

    assert result["new_items"] == 1
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "1001")
        assert row is not None
        assert row.source_item_id == "1001"
        assert row.source_platform == "taobao_sf"
    claimed = repo.claim_seed_detail_item("detail-worker", lease_seconds=30)
    assert claimed is not None
    assert claimed["id"] == "1001"
    assert claimed["item_id"] == "1001"


def test_generic_detail_claim_requires_source_url_instead_of_fabricating_taobao_url(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    repo.initialize()
    policy = GenericSeedScanPolicy(source_platform="catalog_x")
    item_id = policy.storage_item_id("missing-url")
    with repo.session_factory.begin() as session:
        session.add(
            FapaiSeedItem(
                item_id=item_id,
                source_item_id="missing-url",
                source_platform="catalog_x",
                source_payload={"source_item_id": "missing-url"},
            )
        )

    with pytest.raises(ValueError, match="generic seed item requires source URL"):
        repo.claim_seed_detail_item("detail-worker", lease_seconds=30)

    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, item_id)
        assert row is not None
        assert row.status == "pending_detail"
        assert row.detail_leased_by is None

    analysis_policy = GenericSeedScanPolicy(source_platform="catalog_y")
    analysis_item_id = analysis_policy.storage_item_id("missing-analysis-url")
    with repo.session_factory.begin() as session:
        session.add(
            FapaiSeedItem(
                item_id=analysis_item_id,
                source_item_id="missing-analysis-url",
                source_platform="catalog_y",
                status="raw_detail_captured",
                source_payload={"source_item_id": "missing-analysis-url"},
            )
        )

    with pytest.raises(ValueError, match="generic seed item requires source URL"):
        repo.claim_seed_raw_detail_item("analysis-worker", lease_seconds=30)

    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, analysis_item_id)
        assert row is not None
        assert row.status == "raw_detail_captured"
        assert row.detail_leased_by is None


def test_generic_upsert_reuses_legacy_platform_scoped_row(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    policy = GenericSeedScanPolicy(source_platform="catalog_x")
    task = _claim_generic_task(repo, policy, "catalog-x")
    with repo.session_factory.begin() as session:
        session.add(
            FapaiSeedItem(
                item_id="legacy-1",
                source_item_id="legacy-1",
                source_platform="catalog_x",
                source_url="https://catalog_x.example/items/legacy-1",
                source_payload={"id": "legacy-1", "source_platform": "catalog_x"},
            )
        )

    result = _upsert_generic(repo, policy, task, "legacy-1")

    assert result["new_items"] == 0
    assert result["existing_items"] == 1
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(FapaiSeedItem)) == 1
        occurrence = session.scalars(select(FapaiSeedOccurrence)).one()
        assert occurrence.item_id == "legacy-1"


def test_detail_worker_uses_storage_item_id_for_artifacts_and_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_id = GenericSeedScanPolicy(source_platform="catalog_x").storage_item_id("shared-1")
    completed: list[str] = []
    stored: list[str] = []

    class Repository:
        def claim_seed_detail_item(self, *_args, **_kwargs):
            return {
                "id": "shared-1",
                "item_id": storage_id,
                "source_item_id": "shared-1",
                "source_platform": "catalog_x",
                "url": "https://catalog.example/items/shared-1",
            }

        def mark_seed_detail_completed(self, item_id: str, **_kwargs) -> None:
            assert stored == [storage_id]
            completed.append(item_id)

        def seed_queue_counts(self):
            return {}

        def upsert_flat_item(self, item, **kwargs) -> None:
            assert item["id"] == storage_id
            assert item["source_item_id"] == "shared-1"
            assert kwargs["event_payload"]["item_id"] == storage_id
            stored.append(item["id"])

    def process_item(*_args, **_kwargs):
        item_dir = tmp_path / storage_id
        item_dir.mkdir()
        (item_dir / "final.json").write_text(
            json.dumps({"id": storage_id, "source_item_id": "shared-1"}), encoding="utf-8"
        )
        return {"ok": True}

    monkeypatch.setattr(detail_worker, "_collection_pause_state_with_retry", lambda _url: {"paused": False})
    config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="",
        target_success=1,
        max_attempts=1,
        worker_id="detail-worker",
        do_risk=False,
    )

    summary = detail_worker.run_detail_worker_once(
        config,
        repository=Repository(),  # type: ignore[arg-type]
        http_session=object(),
        browser_pages={},
        process_item_func=process_item,
    )

    assert summary["decision"] == "detail_item_completed"
    assert summary["item_id"] == storage_id
    assert summary["final_json_path"] == str(tmp_path / storage_id / "final.json")
    assert completed == [storage_id]
    assert stored == [storage_id]


def test_flat_storage_keeps_platform_scoped_item_ids(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    policy_x = GenericSeedScanPolicy(source_platform="catalog_x")
    policy_y = GenericSeedScanPolicy(source_platform="catalog_y")
    item_id_x = policy_x.storage_item_id("shared-1")
    item_id_y = policy_y.storage_item_id("shared-1")

    for policy, item_id in ((policy_x, item_id_x), (policy_y, item_id_y)):
        repo.upsert_flat_item(
            {
                "id": item_id,
                "item_id": item_id,
                "source_item_id": "shared-1",
                "source_platform": policy.source_platform,
                "source_url": f"https://{policy.source_platform}.example/items/shared-1",
            },
            event_type="detail_worker_completed",
        )

    with repo.session_factory() as session:
        rows = session.scalars(select(PropertyListing)).all()
        assert {row.item_id for row in rows} == {item_id_x, item_id_y}
        assert {row.source_item_id for row in rows} == {"shared-1"}


def test_generic_source_platform_length_is_rejected() -> None:
    with pytest.raises(ValueError, match="at most 32"):
        GenericSeedScanPolicy(source_platform="x" * 33)


def test_generic_repository_normalizes_oversized_source_ids(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    policy = GenericSeedScanPolicy(source_platform="catalog_x")
    task = _claim_generic_task(repo, policy, "catalog-x")
    raw_source_item_id = "external-" + ("x" * 80)
    source_item_id = normalize_source_item_id(raw_source_item_id)

    result = _upsert_generic(repo, policy, task, raw_source_item_id)

    assert result["new_items"] == 1
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, policy.storage_item_id(source_item_id))
        assert row is not None
        assert row.source_item_id == source_item_id
        assert row.source_payload["raw_source_item_id"] == raw_source_item_id
