"""Queue selection remains fair beyond a full SQL candidate window."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, insert, select, update

from src.storage.models import FapaiSeedScanJob, FapaiSeedScanProgress
from src.storage.repository import DatabaseSettings, PropertyRepository
from src.storage.seed_scan_candidates import CANDIDATE_BATCH_SIZE
from tools.test.test_quality_postgres_claims import repository


@pytest.fixture
def queue(tmp_path):
    repo = PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'queue.sqlite3').as_posix()}",
            enabled=True,
            auto_create=True,
            enable_postgis=False,
        )
    )
    repo.initialize()
    yield repo
    repo.engine.dispose()


def populate(repo, count, *, unavailable=None):
    jobs, pages = [], []
    for index in range(count):
        key = f"job-{index:05d}"
        jobs.append(
            dict(
                job_key=key,
                province="P",
                city="C",
                district="D",
                location_code="001",
                category="50025969",
                status="pending",
            )
        )
        page = dict(
            progress_key=key + ":bid",
            job_key=key,
            sort_key="bid_desc",
            st_param="2",
            sort_order=0,
            next_page=(unavailable or {}).get("next_page", 1),
            retry_count=(unavailable or {}).get("retry_count", 0),
            status="pending",
        )
        if unavailable and index < count - 1:
            page.update(unavailable)
        pages.append(page)
    with repo.session_factory.begin() as session:
        session.execute(insert(FapaiSeedScanJob), jobs)
        session.execute(insert(FapaiSeedScanProgress), pages)


@pytest.mark.parametrize("parallel", [False, True])
def test_first_claim_materializes_one_window_not_whole_queue(queue, parallel):
    populate(queue, CANDIDATE_BATCH_SIZE * 4 + 1)
    loaded = []

    def on_load(session, instance):
        if isinstance(instance, (FapaiSeedScanJob, FapaiSeedScanProgress)):
            loaded.append((type(instance), instance))

    event.listen(queue.session_factory, "loaded_as_persistent", on_load)
    try:
        claim = queue.claim_seed_scan_page("worker", parallel_sorts=parallel)
    finally:
        event.remove(queue.session_factory, "loaded_as_persistent", on_load)
    assert claim["job_key"] == "job-00000"
    assert len(loaded) <= CANDIDATE_BATCH_SIZE * 2


@pytest.mark.parametrize("parallel", [False, True])
def test_candidate_window_only_loads_complete_models_for_locked_claim(queue, parallel):
    populate(queue, CANDIDATE_BATCH_SIZE * 2 + 1)
    loaded = []
    queries = []

    def on_load(session, instance):
        if isinstance(instance, (FapaiSeedScanJob, FapaiSeedScanProgress)):
            loaded.append(instance)

    def on_query(conn, cursor, statement, parameters, context, executemany):
        if "JOIN fapai_seed_scan_job" in statement:
            queries.append(statement)

    event.listen(queue.session_factory, "loaded_as_persistent", on_load)
    event.listen(queue.engine, "before_cursor_execute", on_query)
    try:
        claim = queue.claim_seed_scan_page("worker", parallel_sorts=parallel)
    finally:
        event.remove(queue.session_factory, "loaded_as_persistent", on_load)
        event.remove(queue.engine, "before_cursor_execute", on_query)
    assert claim["job_key"] == "job-00000"
    assert len(loaded) == 2
    assert queries
    for statement in queries:
        projection = statement.split("FROM", 1)[0]
        assert "last_fetch_url" not in projection
        assert "last_error" not in projection
        assert "source_url_template" not in projection


def test_breadth_first_covers_shallow_work_without_discarding_deep_history(queue):
    populate(queue, 2)
    with queue.session_factory.begin() as session:
        session.execute(
            update(FapaiSeedScanProgress)
            .where(FapaiSeedScanProgress.job_key == "job-00000")
            .values(next_page=30)
        )
        session.execute(
            update(FapaiSeedScanProgress)
            .where(FapaiSeedScanProgress.job_key == "job-00001")
            .values(next_page=2)
        )
    claim = queue.claim_seed_scan_page(
        "worker", parallel_sorts=True, breadth_first=True
    )
    assert (claim["job_key"], claim["page"]) == ("job-00001", 2)
    queue.complete_seed_scan_page(
        progress_key=claim["progress_key"], page=2, item_count=0, has_next=False
    )
    remaining = queue.claim_seed_scan_page(
        "worker", parallel_sorts=True, breadth_first=True
    )
    assert (remaining["job_key"], remaining["page"]) == ("job-00000", 30)


@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("blocked", ["lease", "cooldown", "exhausted"])
def test_later_work_not_starved_by_full_unavailable_windows(queue, parallel, blocked):
    count = CANDIDATE_BATCH_SIZE * 4 + 1
    if blocked == "lease":
        unavailable = dict(
            status="in_progress",
            leased_by="other",
            lease_until=datetime.utcnow() + timedelta(hours=1),
        )
    elif blocked == "cooldown":
        unavailable = dict(
            last_error="retry later", retry_count=3, updated_at=datetime.utcnow()
        )
    else:
        unavailable = dict(max_page=1, next_page=2)
    populate(queue, count, unavailable=unavailable)
    claim = queue.claim_seed_scan_page(
        "worker",
        parallel_sorts=parallel,
        failure_cooldown_threshold=3,
        failure_cooldown_seconds=1800,
    )
    assert claim["job_key"] == f"job-{count - 1:05d}"
    with queue.session_factory() as session:
        rows = session.scalars(select(FapaiSeedScanProgress)).all()
        assert len(rows) == count
        if blocked == "lease":
            assert sum(row.leased_by == "other" for row in rows) == count - 1
        if blocked == "exhausted":
            assert sum(row.status == "exhausted" for row in rows) == count - 1


@pytest.mark.integration
@pytest.mark.parametrize("parallel", [False, True])
def test_postgres_keyset_reaches_later_window(repository, parallel):
    count = CANDIDATE_BATCH_SIZE + 1
    populate(
        repository,
        count,
        unavailable=dict(
            status="in_progress",
            leased_by="other",
            lease_until=datetime.utcnow() + timedelta(hours=1),
        ),
    )
    claim = repository.claim_seed_scan_page("worker", parallel_sorts=parallel)
    assert claim["job_key"] == f"job-{count - 1:05d}"


@pytest.mark.parametrize("parallel", [False, True])
def test_foreign_policy_window_does_not_hide_owned_work(queue, parallel):
    count = CANDIDATE_BATCH_SIZE + 1
    populate(queue, count)
    last_key = f"job-{count - 1:05d}"
    with queue.session_factory.begin() as session:
        session.execute(
            update(FapaiSeedScanJob)
            .where(FapaiSeedScanJob.job_key != last_key)
            .values(
                metadata_json={
                    "seed_scan_policy": "generic",
                    "source_platform": "fixture",
                }
            )
        )
    claim = queue.claim_seed_scan_page("worker", parallel_sorts=parallel)
    assert claim["job_key"] == last_key


@pytest.mark.parametrize("parallel", [False, True])
def test_single_job_with_many_sorts_is_not_fully_materialized(queue, parallel):
    populate(queue, 1)
    with queue.session_factory.begin() as session:
        session.execute(
            insert(FapaiSeedScanProgress),
            [
                dict(
                    progress_key=f"extra-{index:05d}",
                    job_key="job-00000",
                    sort_key=f"sort-{index}",
                    st_param="2",
                    sort_order=index + 1,
                    next_page=1,
                    status="pending",
                )
                for index in range(CANDIDATE_BATCH_SIZE * 4)
            ],
        )
    loaded = []

    def on_load(session, instance):
        if isinstance(instance, FapaiSeedScanProgress):
            loaded.append(instance)

    event.listen(queue.session_factory, "loaded_as_persistent", on_load)
    try:
        claim = queue.claim_seed_scan_page("worker", parallel_sorts=parallel)
    finally:
        event.remove(queue.session_factory, "loaded_as_persistent", on_load)
    assert claim["sort_key"] == "bid_desc"
    assert len(loaded) <= CANDIDATE_BATCH_SIZE


def test_release_worker_leases_processes_bounded_windows(queue):
    count = CANDIDATE_BATCH_SIZE * 3 + 1
    populate(queue, count)
    lease_until = datetime.utcnow() + timedelta(hours=1)
    with queue.session_factory.begin() as session:
        session.execute(
            update(FapaiSeedScanProgress).values(
                status="in_progress",
                leased_by="worker",
                lease_until=lease_until,
            )
        )

    peak_identity_map = 0

    def on_load(session, instance):
        nonlocal peak_identity_map
        if isinstance(instance, (FapaiSeedScanJob, FapaiSeedScanProgress)):
            peak_identity_map = max(peak_identity_map, len(session.identity_map))

    event.listen(queue.session_factory, "loaded_as_persistent", on_load)
    try:
        released = queue.release_seed_scan_worker_leases("worker")
    finally:
        event.remove(queue.session_factory, "loaded_as_persistent", on_load)

    assert released == {"released": count}
    assert peak_identity_map <= CANDIDATE_BATCH_SIZE * 2
    with queue.session_factory() as session:
        rows = session.scalars(select(FapaiSeedScanProgress)).all()
        assert len(rows) == count
        assert all(row.status == "pending" for row in rows)
        assert all(row.leased_by is None and row.lease_until is None for row in rows)
