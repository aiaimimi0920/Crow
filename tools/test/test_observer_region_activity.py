"""Waiting work and expired leases must not look like active collection."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from src.storage.models import CollectionSeedItem, CollectionSeedScanProgress
from src.storage.repository_context import _utc_now
from tools.test.seed_queue_repository_test_context import (
    _ensure_nansha_job,
    _make_repo,
    _upsert_sample_seed,
)


@pytest.fixture
def repository(tmp_path):
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    yield repo
    repo.engine.dispose()


@pytest.mark.parametrize(
    "mode,label",
    [
        ("pending", "待采集"),
        ("started", "待继续"),
        ("active", "采集中"),
        ("expired", "待继续"),
        ("retry", "等待重试"),
        ("blocked", "存在失败/阻塞"),
    ],
)
def test_links_activity_requires_live_lease(repository, mode, label):
    with repository.session_factory.begin() as session:
        page = session.scalars(select(CollectionSeedScanProgress)).first()
        if mode != "pending":
            page.last_success_page = 1
        if mode in {"active", "expired"}:
            page.status = "in_progress"
            page.leased_by = "worker"
            page.lease_until = _utc_now() + timedelta(
                seconds=60 if mode == "active" else -60
            )
        elif mode == "retry":
            page.last_error = "temporary"
        elif mode == "blocked":
            page.status = "blocked"
    region = repository.collection_observer_regions(stage="links")["regions"][0]
    assert region["status_label"] == label
    assert region["counts"]["active_progress"] == (1 if mode == "active" else 0)
    assert region["completed"] is False


@pytest.mark.parametrize(
    "stage,status", [("details", "in_progress"), ("analysis", "analysis_in_progress")]
)
@pytest.mark.parametrize("valid", [True, False])
def test_item_activity_does_not_inherit_link_activity(repository, stage, status, valid):
    _upsert_sample_seed(repository)
    with repository.session_factory.begin() as session:
        item = session.get(CollectionSeedItem, "1001")
        item.status = status
        item.detail_leased_by = "worker"
        item.detail_lease_until = _utc_now() + timedelta(seconds=60 if valid else -60)
    region = repository.collection_observer_regions(stage=stage)["regions"][0]
    assert region["counts"]["active_items"] == int(valid)
    assert (region["status_label"] == "采集中") is valid
