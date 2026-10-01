"""Refresh seed job state from progress summaries without per-job query loops."""

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CollectionSeedScanJob, CollectionSeedScanProgress


def apply_job_status(
    session: Session, job: CollectionSeedScanJob, statuses: set[str], now: datetime
) -> None:
    if statuses and statuses.issubset({"exhausted"}):
        job.status = "completed"
        job.completed_at = job.completed_at or now
    elif "blocked" in statuses and statuses.issubset({"exhausted", "blocked"}):
        job.status = "blocked"
        job.completed_at = None
    elif "in_progress" in statuses:
        job.status = "in_progress"
        job.completed_at = None
    else:
        job.status = "pending"
        job.completed_at = None
    session.add(job)


def refresh_job_statuses(
    session: Session, job_keys: Iterable[str], now: datetime
) -> None:
    """Caller supplies one bounded maintenance window; no progress ORM rows load."""
    keys = sorted(set(job_keys))
    if not keys:
        return
    jobs = session.scalars(
        select(CollectionSeedScanJob).where(CollectionSeedScanJob.job_key.in_(keys))
    ).all()
    statuses: dict[str, set[str]] = defaultdict(set)
    for job_key, status in session.execute(
        select(CollectionSeedScanProgress.job_key, CollectionSeedScanProgress.status)
        .where(CollectionSeedScanProgress.job_key.in_(keys))
        .distinct()
    ):
        statuses[job_key].add(status)
    for job in jobs:
        apply_job_status(session, job, statuses[job.job_key], now)
