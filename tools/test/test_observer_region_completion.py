"""区域完成必须覆盖链接扫描范围，而不是只看当前已发现的商品。"""

import pytest
from sqlalchemy import event, select

from src.storage.models import CollectionSeedScanJob, CollectionSeedScanProgress
from tools.test.seed_queue_repository_test_context import (
    _ensure_nansha_job,
    _make_repo,
    _upsert_sample_seed,
)


@pytest.fixture
def repository(tmp_path):
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    try:
        yield repo
    finally:
        repo.engine.dispose()


def set_scan_status(repo, status):
    with repo.session_factory.begin() as session:
        job = session.scalars(select(CollectionSeedScanJob)).one()
        job.status = status
        for progress in session.scalars(select(CollectionSeedScanProgress)):
            progress.status = "exhausted" if status == "completed" else status


@pytest.mark.parametrize("stage", ["details", "analysis"])
def test_empty_region_is_complete_only_after_link_scan(repository, stage):
    before = repository.collection_observer_regions(stage=stage)["regions"][0]
    assert before["completed"] is False
    set_scan_status(repository, "completed")
    after = repository.collection_observer_regions(stage=stage)["regions"][0]
    assert after["counts"]["total_items"] == 0
    assert after["completed"] is True
    assert after["status_label"] == "收集完成"


@pytest.mark.parametrize("stage", ["details", "analysis"])
@pytest.mark.parametrize("scan_status", ["pending", "in_progress", "blocked"])
def test_processed_items_do_not_complete_an_unfinished_region(repository, stage, scan_status):
    _upsert_sample_seed(repository)
    repository.mark_seed_detail_completed("1001", final_json_path="final.json")
    set_scan_status(repository, scan_status)
    region = repository.collection_observer_regions(stage=stage)["regions"][0]
    assert region["counts"]["completed_items"] == 1
    assert region["completed"] is False
    expected = "存在失败/阻塞" if scan_status == "blocked" else "采集中"
    assert region["status_label"] == expected


@pytest.mark.parametrize("stage", ["details", "analysis"])
def test_completed_job_does_not_hide_unfinished_progress(repository, stage):
    set_scan_status(repository, "completed")
    with repository.session_factory.begin() as session:
        progress = session.scalars(select(CollectionSeedScanProgress)).first()
        progress.status = "pending"
    region = repository.collection_observer_regions(stage=stage)["regions"][0]
    assert region["completed"] is False


@pytest.mark.parametrize("stage", ["details", "analysis"])
def test_completed_scan_does_not_hide_unprocessed_items(repository, stage):
    _upsert_sample_seed(repository)
    set_scan_status(repository, "completed")
    region = repository.collection_observer_regions(stage=stage)["regions"][0]
    assert region["completed"] is False
    assert region["counts"]["pending"] == 1


@pytest.mark.parametrize("stage", ["details", "analysis"])
def test_region_counts_remain_batched_and_read_only(repository, stage):
    set_scan_status(repository, "completed")
    statements = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lstrip().upper())

    event.listen(repository.engine, "before_cursor_execute", record)
    try:
        assert repository.collection_observer_regions(stage=stage)["regions"][0]["completed"]
    finally:
        event.remove(repository.engine, "before_cursor_execute", record)
    assert len(statements) <= 4
    assert all(statement.startswith("SELECT") for statement in statements)
