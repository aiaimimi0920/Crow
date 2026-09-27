"""Single-job and batch refresh preserve the same persisted status contract."""

from datetime import datetime

import pytest
from sqlalchemy import select

from src.storage.models import FapaiSeedScanJob, FapaiSeedScanProgress
from src.storage.repository import DatabaseSettings, PropertyRepository
from src.storage.seed_scan_job_status import refresh_job_statuses
from tools.test.test_quality_postgres_claims import (
    repository as postgres_repository,  # noqa: F401
)


@pytest.fixture(params=["sqlite", "postgres"])
def repository(request, tmp_path):
    if request.param == "postgres":
        yield request.getfixturevalue("postgres_repository")
        return
    repo = PropertyRepository(
        DatabaseSettings(
            url="sqlite:///" + (tmp_path / "status.sqlite3").as_posix(),
            enabled=True,
            auto_create=True,
            enable_postgis=False,
        )
    )
    repo.initialize()
    try:
        yield repo
    finally:
        repo.engine.dispose()


@pytest.mark.parametrize("batch", [False, True])
def test_refresh_preserves_mixed_progress_and_completion_times(repository, batch):
    previous = datetime(2026, 1, 1)  # noqa: DTZ001 - repository API uses UTC-naive values.
    now = datetime(2026, 2, 1)  # noqa: DTZ001 - repository API uses UTC-naive values.
    cases = {
        "empty": ([], "pending", previous, None),
        "complete": (["exhausted", "exhausted"], "completed", None, now),
        "retained": (["exhausted"], "completed", previous, previous),
        "blocked": (["blocked", "exhausted"], "blocked", previous, None),
        "mixed": (["blocked", "pending"], "pending", previous, None),
        "active": (["in_progress", "blocked"], "in_progress", previous, None),
        "archived": (["archived"], "pending", previous, None),
    }
    with repository.session_factory.begin() as session:
        for key, (statuses, _expected, completed, _at) in cases.items():
            session.add(
                FapaiSeedScanJob(
                    job_key=key,
                    location_code="test",
                    category="test",
                    status="completed",
                    completed_at=completed,
                )
            )
        session.flush()
        for key, (statuses, *_rest) in cases.items():
            for index, status in enumerate(statuses):
                session.add(
                    FapaiSeedScanProgress(
                        progress_key=f"{key}:{index}",
                        job_key=key,
                        sort_key=str(index),
                        st_param=str(index),
                        status=status,
                    )
                )
    with repository.session_factory.begin() as session:
        keys = [*cases, "missing", "active"]
        if batch:
            refresh_job_statuses(session, keys, now)
        else:
            for key in keys:
                repository._refresh_seed_scan_job_status(session, key, now)
    with repository.session_factory() as session:
        jobs = {job.job_key: job for job in session.scalars(select(FapaiSeedScanJob))}
        assert set(jobs) == set(cases)
        for key, (_statuses, expected, _before, completed_at) in cases.items():
            assert jobs[key].status == expected
            assert jobs[key].completed_at == completed_at
