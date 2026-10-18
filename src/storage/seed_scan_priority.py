"""Prefer finishing started scan groups without starving old deep pages."""

from datetime import timedelta

from sqlalchemy import case, func, select

from .models import CollectionSeedScanProgress

WAIT_PROTECTION_SECONDS = 1800


def closure_groups():
    """Aggregate within a job, never mix ownership across source policies."""
    page = CollectionSeedScanProgress
    return (
        select(
            page.job_key.label("job_key"),
            func.max(
                case(
                    ((page.last_success_page > 0) | (page.status == "exhausted"), 1),
                    else_=0,
                )
            ).label("started"),
            func.sum(case((page.status != "exhausted", 1), else_=0)).label("remaining"),
        )
        .where(page.status != "archived")
        .group_by(page.job_key)
        .subquery()
    )


def closure_order(groups, now):
    page = CollectionSeedScanProgress
    # updated_at measures queue touch (including claims/failures), not success.
    touched = func.coalesce(page.updated_at, page.created_at, now)
    overdue = touched <= now - timedelta(seconds=WAIT_PROTECTION_SECONDS)
    return (
        case((overdue, 0), else_=1),
        case((overdue, touched), else_=now),
        case((groups.c.started > 0, 0), else_=1),
        case((groups.c.started > 0, groups.c.remaining), else_=0),
    )
