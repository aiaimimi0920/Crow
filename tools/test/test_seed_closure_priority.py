"""Started scan groups close while old deep/unstarted work remains eligible."""

from datetime import timedelta

import pytest
from sqlalchemy import insert, select

from src.storage.models import CollectionSeedScanJob as Job
from src.storage.models import CollectionSeedScanProgress as Page
from src.storage.repository_context import _utc_now, use_repository_clock
from tools.test.seed_queue_repository_test_context import _make_repo


@pytest.fixture
def queue(tmp_path):
    repo = _make_repo(tmp_path)
    repo.initialize()
    yield repo
    repo.engine.dispose()


def group(repo, key, *, done=0, pending=1, page=1, age=0, leased=False, failed=False):
    now = _utc_now()
    with repo.session_factory.begin() as session:
        session.add(
            Job(job_key=key, location_code=key, category="50025969", status="pending")
        )
        session.flush()
        session.execute(
            insert(Page),
            [
                {
                    "job_key": key,
                    "progress_key": f"{key}:{i}",
                    "sort_key": str(i),
                    "sort_order": i,
                    "st_param": "1",
                    "status": "exhausted"
                    if i < done
                    else "in_progress"
                    if leased
                    else "pending",
                    "next_page": page,
                    "last_success_page": page - 1 if page > 1 else None,
                    "leased_by": "other" if leased else None,
                    "lease_until": now + timedelta(hours=1) if leased else None,
                    "last_error": "temporary" if failed else None,
                    "retry_count": 3 if failed else 0,
                    "updated_at": now - timedelta(seconds=age),
                }
                for i in range(done + pending)
            ],
        )


def claim(repo):
    return repo.claim_seed_scan_page(
        "worker",
        parallel_sorts=True,
        breadth_first=True,
        failure_cooldown_threshold=3,
        failure_cooldown_seconds=3600,
    )


def test_started_group_finishes_before_new_shallow_groups(queue):
    group(queue, "bincheng", done=9, pending=3, page=40)
    group(queue, "yangxin", done=1, pending=11)
    group(queue, "new")
    for _ in range(3):
        task = claim(queue)
        assert task["job_key"] == "bincheng"
        queue.complete_seed_scan_page(
            progress_key=task["progress_key"],
            page=task["page"],
            item_count=0,
            has_next=False,
        )
    assert claim(queue)["job_key"] == "yangxin"


def test_wait_protection_advances_deep_work_despite_new_shallow_arrivals(queue):
    now = _utc_now()
    with use_repository_clock(lambda: now):
        group(queue, "old-deep", page=80, age=1900)
        for i in range(8):
            group(queue, f"fresh-{i}", done=11, pending=1)
        assert claim(queue)["job_key"] == "old-deep"


def test_normalizing_a_whole_window_does_not_lose_the_last_claim(queue):
    group(queue, "many", done=1, pending=130)
    with queue.session_factory.begin() as session:
        for row in session.scalars(select(Page).where(Page.status == "pending")):
            row.max_page = 1
            row.next_page = 2
        session.get(Page, "many:130").max_page = 3
    task = claim(queue)
    assert task is not None
    assert task["progress_key"] == "many:130"


def test_archived_and_foreign_jobs_never_receive_claims(queue):
    group(queue, "archived", done=11, age=7200)
    group(queue, "foreign", done=11, age=7200)
    group(queue, "owned")
    with queue.session_factory.begin() as session:
        session.get(Job, "archived").status = "archived"
        session.get(Job, "foreign").metadata_json = {
            "seed_scan_policy": "generic",
            "source_platform": "fixture",
        }
    assert claim(queue)["job_key"] == "owned"


def test_unstarted_old_work_is_not_starved_by_started_groups(queue):
    group(queue, "old-new", age=1900)
    group(queue, "almost-done", done=11)
    assert claim(queue)["job_key"] == "old-new"


def test_age_protection_keeps_oldest_first_not_smallest_remaining(queue):
    group(queue, "old-large", page=80, pending=12, age=7200)
    group(queue, "new-small", done=11, age=1900)
    assert claim(queue)["job_key"] == "old-large"


def test_closure_does_not_override_leases_or_failure_cooldown(queue):
    group(queue, "leased", done=11, page=40, age=1900, leased=True)
    group(queue, "cooling", done=11, page=40, age=1900, failed=True)
    group(queue, "available")
    assert claim(queue)["job_key"] == "available"
    with queue.session_factory() as session:
        assert (
            session.scalars(
                select(Page).where(Page.job_key == "cooling", Page.status == "pending")
            )
            .one()
            .retry_count
            == 3
        )
