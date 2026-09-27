from tools.test.seed_queue_repository_test_context import *  # noqa: F401,F403
from src.storage.repository_seed_scan_jobs import SEED_SCAN_MAINTENANCE_BATCH_SIZE


def test_reset_seed_link_region_uses_bounded_windows(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.initialize()
    reset_count = SEED_SCAN_MAINTENANCE_BATCH_SIZE * 2 + 1
    jobs = [
        {
            "job_key": f"reset-{index:04d}",
            "province": "广东",
            "city": "广州",
            "district": "南沙",
            "location_code": "440116",
            "category": "50025969",
            "status": "completed",
        }
        for index in range(reset_count)
    ]
    progress = [
        {
            "progress_key": f"reset-{index:04d}::default",
            "job_key": f"reset-{index:04d}",
            "sort_key": "default",
            "sort_name": "默认排序",
            "st_param": "0",
            "sort_order": 0,
            "next_page": 9,
            "last_success_page": 8,
            "status": "exhausted",
            "leased_by": "worker",
            "lease_until": datetime.now() + timedelta(minutes=5),
            "retry_count": 3,
            "last_error": "old error",
        }
        for index in range(reset_count)
    ]
    with repo.session_factory.begin() as session:
        session.execute(insert(FapaiSeedScanJob), jobs)
        session.execute(insert(FapaiSeedScanProgress), progress)

    peak_loaded = 0

    def on_load(session, instance) -> None:
        nonlocal peak_loaded
        if isinstance(instance, (FapaiSeedScanJob, FapaiSeedScanProgress)):
            peak_loaded = max(peak_loaded, len(session.identity_map))

    event.listen(repo.session_factory, "loaded_as_persistent", on_load)
    try:
        result = repo.reset_seed_link_region("440116")
    finally:
        event.remove(repo.session_factory, "loaded_as_persistent", on_load)

    assert result == {
        "ok": True,
        "location_code": "440116",
        "reset": {"jobs": reset_count, "progress": reset_count},
    }
    assert peak_loaded <= SEED_SCAN_MAINTENANCE_BATCH_SIZE * 2
    with repo.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(FapaiSeedScanJob)
                .where(FapaiSeedScanJob.status == "pending")
            )
            == reset_count
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(FapaiSeedScanProgress)
                .where(FapaiSeedScanProgress.status == "pending")
            )
            == reset_count
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(FapaiSeedScanProgress)
                .where(FapaiSeedScanProgress.leased_by.is_not(None))
            )
            == 0
        )


def test_archive_seed_scan_jobs_except_uses_bounded_windows(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.initialize()
    stale_count = SEED_SCAN_MAINTENANCE_BATCH_SIZE * 2 + 1
    jobs = [
        {
            "job_key": f"stale-{index:04d}",
            "province": "广东",
            "city": "广州",
            "district": "南沙",
            "location_code": "440115",
            "category": "50025969",
            "status": "pending",
            "metadata_json": {},
        }
        for index in range(stale_count)
    ]
    progress = [
        {
            "progress_key": f"stale-{index:04d}::default",
            "job_key": f"stale-{index:04d}",
            "sort_key": "default",
            "sort_name": "默认排序",
            "st_param": "0",
            "sort_order": 0,
            "next_page": 1,
            "status": "pending",
            "leased_by": "worker",
            "lease_until": datetime.now() + timedelta(minutes=5),
        }
        for index in range(stale_count)
    ]
    with repo.session_factory.begin() as session:
        session.execute(insert(FapaiSeedScanJob), jobs)
        session.execute(insert(FapaiSeedScanProgress), progress)

    peak_loaded = 0

    def on_load(session, instance) -> None:
        nonlocal peak_loaded
        if isinstance(instance, (FapaiSeedScanJob, FapaiSeedScanProgress)):
            peak_loaded = max(peak_loaded, len(session.identity_map))

    event.listen(repo.session_factory, "loaded_as_persistent", on_load)
    try:
        result = repo.archive_seed_scan_jobs_except(["active-job"])
    finally:
        event.remove(repo.session_factory, "loaded_as_persistent", on_load)

    assert result == {
        "active_job_count": 1,
        "archived_jobs": stale_count,
        "archived_progress": stale_count,
    }
    assert peak_loaded <= SEED_SCAN_MAINTENANCE_BATCH_SIZE * 2
    with repo.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(FapaiSeedScanJob)
                .where(FapaiSeedScanJob.status == "archived")
            )
            == stale_count
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(FapaiSeedScanProgress)
                .where(FapaiSeedScanProgress.status == "archived")
            )
            == stale_count
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(FapaiSeedScanProgress)
                .where(FapaiSeedScanProgress.leased_by.is_not(None))
            )
            == 0
        )

    second = repo.archive_seed_scan_jobs_except(["active-job"])
    assert second["archived_jobs"] == 0
    assert second["archived_progress"] == 0


def test_release_seed_scan_worker_leases_uses_bounded_windows(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.initialize()
    release_count = SEED_SCAN_MAINTENANCE_BATCH_SIZE * 2 + 1
    jobs = [
        {
            "job_key": f"release-{index:04d}",
            "province": "广东",
            "city": "广州",
            "district": "南沙",
            "location_code": "440116",
            "category": "50025969",
            "status": "in_progress",
        }
        for index in range(release_count)
    ]
    jobs.append(
        {
            "job_key": "release-other",
            "province": "广东",
            "city": "广州",
            "district": "南沙",
            "location_code": "440116",
            "category": "50025969",
            "status": "in_progress",
        }
    )
    lease_until = datetime.now() + timedelta(minutes=5)
    progress = [
        {
            "progress_key": f"release-{index:04d}::default",
            "job_key": f"release-{index:04d}",
            "sort_key": "default",
            "sort_name": "默认排序",
            "st_param": "0",
            "sort_order": 0,
            "next_page": 1,
            "status": "in_progress",
            "leased_by": "worker-a",
            "lease_until": lease_until,
        }
        for index in range(release_count)
    ]
    progress.append(
        {
            "progress_key": "release-other::default",
            "job_key": "release-other",
            "sort_key": "default",
            "sort_name": "默认排序",
            "st_param": "0",
            "sort_order": 0,
            "next_page": 1,
            "status": "in_progress",
            "leased_by": "worker-b",
            "lease_until": lease_until,
        }
    )
    with repo.session_factory.begin() as session:
        session.execute(insert(FapaiSeedScanJob), jobs)
        session.execute(insert(FapaiSeedScanProgress), progress)

    peak_loaded = 0

    def on_load(session, instance) -> None:
        nonlocal peak_loaded
        if isinstance(instance, (FapaiSeedScanJob, FapaiSeedScanProgress)):
            peak_loaded = max(peak_loaded, len(session.identity_map))

    selects = []

    def count_select(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(repo.session_factory, "loaded_as_persistent", on_load)
    event.listen(repo.engine, "before_cursor_execute", count_select)
    try:
        result = repo.release_seed_scan_worker_leases("worker-a")
    finally:
        event.remove(repo.session_factory, "loaded_as_persistent", on_load)
        event.remove(repo.engine, "before_cursor_execute", count_select)

    assert result == {"released": release_count}
    windows = (
        release_count + SEED_SCAN_MAINTENANCE_BATCH_SIZE - 1
    ) // SEED_SCAN_MAINTENANCE_BATCH_SIZE
    assert len(selects) <= 3 * windows + 1
    assert peak_loaded <= SEED_SCAN_MAINTENANCE_BATCH_SIZE * 2
    with repo.session_factory() as session:
        released_rows = session.scalars(
            select(FapaiSeedScanProgress).where(
                FapaiSeedScanProgress.job_key.like("release-%"),
                FapaiSeedScanProgress.job_key != "release-other",
            )
        ).all()
        assert len(released_rows) == release_count
        assert all(row.status == "pending" for row in released_rows)
        assert all(row.leased_by is None for row in released_rows)
        assert all(row.lease_until is None for row in released_rows)
        other = session.get(FapaiSeedScanProgress, "release-other::default")
        assert other is not None
        assert other.status == "in_progress"
        assert other.leased_by == "worker-b"
        assert other.lease_until is not None
        assert all(
            row.status == "pending"
            for row in session.scalars(
                select(FapaiSeedScanJob).where(
                    FapaiSeedScanJob.job_key.like("release-%"),
                    FapaiSeedScanJob.job_key != "release-other",
                )
            )
        )
        assert session.get(FapaiSeedScanJob, "release-other").status == "in_progress"

    assert repo.release_seed_scan_worker_leases("worker-a") == {"released": 0}
