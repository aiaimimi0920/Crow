"""批量读取区域链接扫描范围，供三个采集阶段共用完成依据。"""

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .models import CollectionSeedScanJob, CollectionSeedScanProgress
from .repository_context import _utc_now


def region_link_counts(session: Session) -> dict[str, dict[str, int]]:
    jobs: dict[str, dict[str, int]] = {}
    for code, status, count in session.execute(
        select(
            CollectionSeedScanJob.location_code,
            CollectionSeedScanJob.status,
            func.count(CollectionSeedScanJob.job_key),
        )
        .where(CollectionSeedScanJob.status != "archived")
        .group_by(CollectionSeedScanJob.location_code, CollectionSeedScanJob.status)
    ):
        jobs.setdefault(str(code or "").strip(), {})[str(status)] = int(count or 0)

    progress: dict[str, dict[str, int]] = {}
    activity: dict[str, dict[str, int]] = {}
    page = CollectionSeedScanProgress
    now = _utc_now()
    for code, status, count, active, started, retrying in session.execute(
        select(
            CollectionSeedScanJob.location_code,
            CollectionSeedScanProgress.status,
            func.count(CollectionSeedScanProgress.progress_key),
            func.sum(
                case(
                    (
                        (page.status == "in_progress")
                        & (page.lease_until > now)
                        & page.leased_by.is_not(None),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    ((page.last_success_page > 0) | (page.status == "exhausted"), 1),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    ((page.status == "pending") & page.last_error.is_not(None), 1),
                    else_=0,
                )
            ),
        )
        .join(
            CollectionSeedScanJob,
            CollectionSeedScanProgress.job_key == CollectionSeedScanJob.job_key,
        )
        .where(
            CollectionSeedScanJob.status != "archived",
            CollectionSeedScanProgress.status != "archived",
        )
        .group_by(
            CollectionSeedScanJob.location_code, CollectionSeedScanProgress.status
        )
    ):
        progress.setdefault(str(code or "").strip(), {})[str(status)] = int(count or 0)
        values = activity.setdefault(
            str(code or "").strip(),
            {"active_progress": 0, "started_progress": 0, "retrying_progress": 0},
        )
        for key, value in zip(values, (active, started, retrying)):
            values[key] += int(value or 0)

    result = {}
    for code, job in jobs.items():
        scan = progress.get(code, {})
        result[code] = {
            "total_jobs": sum(job.values()),
            "pending_jobs": job.get("pending", 0),
            "in_progress_jobs": job.get("in_progress", 0),
            "completed_jobs": job.get("completed", 0),
            "blocked_jobs": job.get("blocked", 0),
            "total_progress": sum(scan.values()),
            "pending_progress": scan.get("pending", 0),
            "in_progress_progress": scan.get("in_progress", 0),
            "exhausted_progress": scan.get("exhausted", 0),
            "blocked_progress": scan.get("blocked", 0),
            **activity.get(code, {}),
        }
    return result
