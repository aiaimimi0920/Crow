"""Bounded, ordered candidate reads for seed-page claims."""

from collections.abc import Iterator
from typing import NamedTuple

from sqlalchemy import case, func, select, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from src.collection.seed_scan_policy import SeedScanPolicy

from .models import CollectionSeedScanJob, CollectionSeedScanProgress

CANDIDATE_BATCH_SIZE = 128


class SeedPageCandidate(NamedTuple):
    progress_key: str
    job_key: str


class SeedJobCandidate(NamedTuple):
    job_key: str
    metadata_json: dict[str, object] | None


def seed_scan_candidates(
    session: Session,
    policy: SeedScanPolicy,
    *,
    parallel_sorts: bool,
    blocked_job_keys: set[str],
    breadth_first: bool = False,
) -> Iterator[tuple[SeedPageCandidate, SeedJobCandidate]]:
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
    if parallel_sorts and breadth_first:
        # Cover shallow pages across regions before repeatedly scanning a deep
        # historical tail. Existing per-region order remains the default.
        order = (progress.next_page, *order)
    query = (
        # Only the eventually locked page/job need their complete payloads.
        select(progress.progress_key, progress.job_key, job.metadata_json, *order)
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
        cursor = tuple(rows[-1][3:])
        for row in rows:
            page = SeedPageCandidate(row[0], row[1])
            owner = SeedJobCandidate(row[1], row[2])
            if owner.job_key in blocked_job_keys:
                continue
            if not policy.owns_job(owner.job_key, owner.metadata_json):
                continue
            yield page, owner
        if len(rows) < CANDIDATE_BATCH_SIZE:
            return
