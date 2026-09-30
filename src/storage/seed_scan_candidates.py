"""Bounded, ordered candidate reads for seed-page claims."""

from collections.abc import Iterator

from sqlalchemy import case, func, select, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from src.collection.seed_scan_policy import SeedScanPolicy

from .models import CollectionSeedScanJob, CollectionSeedScanProgress

CANDIDATE_BATCH_SIZE = 128


def seed_scan_candidates(
    session: Session,
    policy: SeedScanPolicy,
    *,
    parallel_sorts: bool,
    blocked_job_keys: set[str],
) -> Iterator[tuple[CollectionSeedScanProgress, CollectionSeedScanJob]]:
    job, progress = CollectionSeedScanJob, CollectionSeedScanProgress
    categories = session.scalars(select(job.category).distinct()).all()
    if not categories:
        return
    category_order = {
        category: policy.category_order(category) for category in categories
    }
    rank = case(
        {key: order[0] for key, order in category_order.items()},
        value=job.category,
        else_=10_000,
    )
    category = case(
        {key: order[1] for key, order in category_order.items()},
        value=job.category,
        else_=job.category,
    )
    scope = (
        func.trim(func.coalesce(job.province, "")),
        func.trim(func.coalesce(job.city, "")),
        func.trim(func.coalesce(job.district, "")),
        func.trim(func.coalesce(job.location_code, "")),
        rank,
        category,
    )
    order: tuple[ColumnElement[object], ...]
    if parallel_sorts:
        order = (
            *scope,
            progress.retry_count,
            progress.next_page,
            job.job_key,
            progress.sort_order,
            progress.progress_key,
        )
    else:
        order = (
            *scope,
            job.job_key,
            progress.sort_order,
            progress.next_page,
            progress.progress_key,
        )
    query = (
        select(progress, job, *order)
        .join(job, progress.job_key == job.job_key)
        .where(progress.status.in_(("pending", "in_progress")))
        .order_by(*order)
        .limit(CANDIDATE_BATCH_SIZE)
    )
    cursor = None
    while True:
        window = query
        if cursor is not None:
            window = window.where(tuple_(*order) > tuple_(*cursor))
        # A full window of leased or foreign-policy jobs must not starve later work.
        rows = session.execute(window).all()
        if not rows:
            return
        cursor = tuple(rows[-1][2:])
        for row in rows:
            page, owner = row[0], row[1]
            if owner.job_key in blocked_job_keys:
                continue
            if not policy.owns_job(owner.job_key, owner.metadata_json):
                continue
            yield page, owner
        if len(rows) < CANDIDATE_BATCH_SIZE:
            return
