"""批量读取区域链接扫描范围，供三个采集阶段共用完成依据。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import CollectionSeedScanJob, CollectionSeedScanProgress


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
    for code, status, count in session.execute(
        select(
            CollectionSeedScanJob.location_code,
            CollectionSeedScanProgress.status,
            func.count(CollectionSeedScanProgress.progress_key),
        )
        .join(CollectionSeedScanJob, CollectionSeedScanProgress.job_key == CollectionSeedScanJob.job_key)
        .where(
            CollectionSeedScanJob.status != "archived",
            CollectionSeedScanProgress.status != "archived",
        )
        .group_by(CollectionSeedScanJob.location_code, CollectionSeedScanProgress.status)
    ):
        progress.setdefault(str(code or "").strip(), {})[str(status)] = int(count or 0)

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
        }
    return result
