from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .models import (
    CollectionSeedItem,
    CollectionSeedOccurrence,
    CollectionSeedScanJob,
    CollectionSeedScanProgress,
)
from .repository_context import _load_taobao_region_override_filter, _utc_now
from .repository_seed_scan_jobs import SEED_SCAN_MAINTENANCE_BATCH_SIZE


class RepositoryObserverRegionsMixin:
    def _collection_observer_stage_clauses(self, stage: str):
        normalized = (stage or "links").strip().lower()
        if normalized == "details":
            return [
                CollectionSeedItem.status.in_(
                    (
                        "raw_detail_captured",
                        "analysis_in_progress",
                        "analysis_failed",
                        "analysis_blocked",
                    )
                )
            ]
        if normalized == "analysis":
            return [CollectionSeedItem.status == "detail_completed"]
        return [CollectionSeedItem.status.in_(("pending_detail", "in_progress", "detail_failed", "detail_blocked"))]

    def _latest_seed_occurrence_payload(self, session: Session, item_id: str) -> Dict[str, Any] | None:
        occurrence = session.scalars(
            select(CollectionSeedOccurrence)
            .join(CollectionSeedScanJob, CollectionSeedOccurrence.job_key == CollectionSeedScanJob.job_key)
            .where(
                CollectionSeedOccurrence.item_id == str(item_id),
                CollectionSeedScanJob.status != "archived",
            )
            .order_by(CollectionSeedOccurrence.seen_at.desc(), CollectionSeedOccurrence.id.desc())
            .limit(1)
        ).first()
        if occurrence is None:
            occurrence = session.scalars(
                select(CollectionSeedOccurrence)
                .where(CollectionSeedOccurrence.item_id == str(item_id))
                .order_by(CollectionSeedOccurrence.seen_at.desc(), CollectionSeedOccurrence.id.desc())
                .limit(1)
            ).first()
        if occurrence is None:
            return None
        job = session.get(CollectionSeedScanJob, occurrence.job_key)
        return self._seed_occurrence_payload(occurrence, job)

    def _latest_seed_occurrence_payloads(self, session: Session, item_ids) -> dict:
        if not item_ids:
            return {}
        # Prefer a non-archived job, even when an archived occurrence is newer.
        ranked = (
            select(
                CollectionSeedOccurrence.id,
                func.row_number().over(
                    partition_by=CollectionSeedOccurrence.item_id,
                    order_by=(
                        case((CollectionSeedScanJob.status != "archived", 0), else_=1),
                        CollectionSeedOccurrence.seen_at.desc(), CollectionSeedOccurrence.id.desc(),
                    ),
                ).label("position"),
            )
            .outerjoin(CollectionSeedScanJob, CollectionSeedOccurrence.job_key == CollectionSeedScanJob.job_key)
            .where(CollectionSeedOccurrence.item_id.in_(item_ids))
            .subquery()
        )
        rows = session.execute(
            select(CollectionSeedOccurrence, CollectionSeedScanJob)
            .join(ranked, ranked.c.id == CollectionSeedOccurrence.id)
            .outerjoin(CollectionSeedScanJob, CollectionSeedOccurrence.job_key == CollectionSeedScanJob.job_key)
            .where(ranked.c.position == 1)
        ).all()
        return {occurrence.item_id: self._seed_occurrence_payload(occurrence, job) for occurrence, job in rows}

    def _seed_occurrence_payload(self, occurrence, job) -> dict:
        return {
            "id": occurrence.id,
            "job_key": occurrence.job_key,
            "location_code": job.location_code if job is not None else None,
            "province": job.province if job is not None else None,
            "city": job.city if job is not None else None,
            "district": job.district if job is not None else None,
            "progress_key": occurrence.progress_key,
            "sort_key": occurrence.sort_key,
            "sort_name": occurrence.sort_name,
            "st_param": occurrence.st_param,
            "page": occurrence.page,
            "rank": occurrence.rank,
            "source_page_url": occurrence.source_page_url,
            "source_final_url": occurrence.source_final_url,
            "seen_at": self._fmt_dt(occurrence.seen_at),
        }

    def _seed_item_observer_payload(self, session: Session, row: CollectionSeedItem, occurrences: dict | None = None) -> Dict[str, Any]:
        return {
            "item_id": row.item_id,
            "source_item_id": row.source_item_id,
            "source_platform": row.source_platform,
            "source_url": row.source_url,
            "title": row.title,
            "status": row.status,
            "first_seen_job_key": row.first_seen_job_key,
            "first_seen_sort_key": row.first_seen_sort_key,
            "first_seen_at": self._fmt_dt(row.first_seen_at),
            "last_seen_at": self._fmt_dt(row.last_seen_at),
            "updated_at": self._fmt_dt(row.updated_at),
            "detail_attempt_count": int(row.detail_attempt_count or 0),
            "detail_last_error": row.detail_last_error,
            "detail_leased_by": row.detail_leased_by,
            "detail_lease_until": self._fmt_dt(row.detail_lease_until),
            "detail_completed_at": self._fmt_dt(row.detail_completed_at),
            "final_json_path": row.final_json_path,
            "selected_json_path": row.selected_json_path,
            "source_payload": dict(row.source_payload or {}),
            "artifacts": self._seed_artifacts_from_row(row),
            "latest_occurrence": occurrences.get(row.item_id) if occurrences is not None else self._latest_seed_occurrence_payload(session, row.item_id),
        }

    @staticmethod
    def _region_label(province: str | None, city: str | None, district: str | None, location_code: str) -> str:
        parts = [str(value).strip() for value in (city, district) if str(value or "").strip()]
        if parts:
            return " ".join(parts)
        if province:
            return str(province)
        return f"地区代码 {location_code}"

    @staticmethod
    def _region_stage_status(stage: str, counts: Dict[str, int]) -> tuple[bool, str]:
        if stage == "links":
            total_jobs = int(counts.get("total_jobs", 0) or 0)
            total_progress = int(counts.get("total_progress", 0) or 0)
            blocked = int(counts.get("blocked_progress", 0) or 0) + int(counts.get("blocked_jobs", 0) or 0)
            pending = (
                int(counts.get("pending_progress", 0) or 0)
                + int(counts.get("in_progress_progress", 0) or 0)
                + int(counts.get("pending_jobs", 0) or 0)
                + int(counts.get("in_progress_jobs", 0) or 0)
            )
            exhausted = int(counts.get("exhausted_progress", 0) or 0)
            completed_jobs = int(counts.get("completed_jobs", 0) or 0)
            completed = total_jobs > 0 and total_progress > 0 and blocked == 0 and pending == 0 and exhausted == total_progress and completed_jobs == total_jobs
            if completed:
                return True, "收集完成"
            if blocked:
                return False, "存在失败/阻塞"
            if total_progress == 0 or pending == 0:
                return False, "待采集"
            return False, "采集中"

        total_items = int(counts.get("total_items", 0) or 0)
        failed = int(counts.get("failed", 0) or 0)
        blocked = int(counts.get("blocked", 0) or 0)
        pending = int(counts.get("pending", 0) or 0)
        completed_items = int(counts.get("completed_items", 0) or 0)
        completed = total_items > 0 and completed_items == total_items and failed == 0 and blocked == 0 and pending == 0
        if completed:
            return True, "收集完成"
        if failed or blocked:
            return False, "存在失败/阻塞"
        if total_items == 0:
            return False, "待采集"
        return False, "采集中"

    def collection_observer_regions(self, *, stage: str = "links") -> Dict[str, Any]:
        normalized_stage = (stage or "links").strip().lower()
        if normalized_stage not in {"links", "details", "analysis"}:
            normalized_stage = "links"
        if not self.enabled:
            return {"ok": True, "stage": normalized_stage, "regions": []}
        self.initialize()
        with self.session_factory() as session:
            region_rows = session.execute(
                select(
                    CollectionSeedScanJob.location_code,
                    func.min(CollectionSeedScanJob.province),
                    func.min(CollectionSeedScanJob.city),
                    func.min(CollectionSeedScanJob.district),
                )
                .where(CollectionSeedScanJob.status != "archived")
                .group_by(CollectionSeedScanJob.location_code)
                .order_by(
                    func.min(CollectionSeedScanJob.province),
                    func.min(CollectionSeedScanJob.city),
                    CollectionSeedScanJob.location_code,
                    func.min(CollectionSeedScanJob.district),
                )
            ).all()
            taobao_override_codes, taobao_replace_admin_provinces = _load_taobao_region_override_filter()
            if normalized_stage == "links":
                job_counts_by_code: dict[str, dict[str, int]] = {}
                for location_code, status, count_value in session.execute(
                    select(
                        CollectionSeedScanJob.location_code,
                        CollectionSeedScanJob.status,
                        func.count(CollectionSeedScanJob.job_key),
                    )
                    .where(CollectionSeedScanJob.status != "archived")
                    .group_by(CollectionSeedScanJob.location_code, CollectionSeedScanJob.status)
                ):
                    code = str(location_code or "").strip()
                    if not code:
                        continue
                    job_counts_by_code.setdefault(code, {})[str(status)] = int(count_value or 0)

                progress_counts_by_code: dict[str, dict[str, int]] = {}
                for location_code, status, count_value in session.execute(
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
                    code = str(location_code or "").strip()
                    if not code:
                        continue
                    progress_counts_by_code.setdefault(code, {})[str(status)] = int(count_value or 0)
                item_status_counts_by_code: dict[str, dict[str, int]] = {}
            else:
                job_counts_by_code = {}
                progress_counts_by_code = {}
                item_status_counts_by_code = {}
                for location_code, status, count_value in session.execute(
                    select(
                        CollectionSeedScanJob.location_code,
                        CollectionSeedItem.status,
                        func.count(func.distinct(CollectionSeedItem.item_id)),
                    )
                    .join(CollectionSeedOccurrence, CollectionSeedOccurrence.item_id == CollectionSeedItem.item_id)
                    .join(CollectionSeedScanJob, CollectionSeedOccurrence.job_key == CollectionSeedScanJob.job_key)
                    .where(CollectionSeedScanJob.status != "archived")
                    .group_by(CollectionSeedScanJob.location_code, CollectionSeedItem.status)
                ):
                    code = str(location_code or "").strip()
                    if not code:
                        continue
                    item_status_counts_by_code.setdefault(code, {})[str(status)] = int(count_value or 0)
            regions: list[Dict[str, Any]] = []
            for location_code, province, city, district in region_rows:
                code = str(location_code or "").strip()
                if not code:
                    continue
                if (
                    taobao_replace_admin_provinces
                    and str(province or "").strip() in taobao_replace_admin_provinces
                    and code not in taobao_override_codes
                ):
                    continue
                counts: Dict[str, int] = {}
                if normalized_stage == "links":
                    job_counts = job_counts_by_code.get(code, {})
                    progress_counts = progress_counts_by_code.get(code, {})
                    counts = {
                        "total_jobs": sum(job_counts.values()),
                        "pending_jobs": job_counts.get("pending", 0),
                        "in_progress_jobs": job_counts.get("in_progress", 0),
                        "completed_jobs": job_counts.get("completed", 0),
                        "blocked_jobs": job_counts.get("blocked", 0),
                        "total_progress": sum(progress_counts.values()),
                        "pending_progress": progress_counts.get("pending", 0),
                        "in_progress_progress": progress_counts.get("in_progress", 0),
                        "exhausted_progress": progress_counts.get("exhausted", 0),
                        "blocked_progress": progress_counts.get("blocked", 0),
                    }
                else:
                    status_counts = item_status_counts_by_code.get(code, {})
                    total_items = sum(status_counts.values())
                    if normalized_stage == "details":
                        completed_statuses = {
                            "raw_detail_captured",
                            "analysis_in_progress",
                            "analysis_failed",
                            "analysis_blocked",
                            "detail_completed",
                        }
                        failed = status_counts.get("detail_failed", 0)
                        blocked = status_counts.get("detail_blocked", 0)
                    else:
                        completed_statuses = {"detail_completed"}
                        failed = sum(value for key, value in status_counts.items() if key.endswith("_failed"))
                        blocked = sum(value for key, value in status_counts.items() if key.endswith("_blocked"))
                    completed_items = sum(status_counts.get(status, 0) for status in completed_statuses)
                    counts = {
                        "total_items": total_items,
                        "completed_items": completed_items,
                        "pending": max(0, total_items - completed_items - failed - blocked),
                        "failed": failed,
                        "blocked": blocked,
                        "by_status": status_counts,
                    }
                completed, status_label = self._region_stage_status(normalized_stage, counts)
                regions.append(
                    {
                        "location_code": code,
                        "province": province,
                        "city": city,
                        "district": district,
                        "label": self._region_label(province, city, district, code),
                        "completed": completed,
                        "status_label": status_label,
                        "counts": counts,
                    }
                )
            return {"ok": True, "stage": normalized_stage, "regions": regions}

    def reset_seed_link_region(self, location_code: str) -> Dict[str, Any]:
        safe_location_code = str(location_code or "").strip()
        if not self.enabled or not safe_location_code:
            return {"ok": False, "location_code": safe_location_code, "error": "location_code is required"}
        self.initialize()
        now = _utc_now()
        reset_jobs = 0
        reset_progress = 0
        with self.session_factory.begin() as session:
            last_job_key: str | None = None
            while True:
                job_query = select(CollectionSeedScanJob).where(
                    CollectionSeedScanJob.location_code == safe_location_code
                )
                if last_job_key is not None:
                    job_query = job_query.where(CollectionSeedScanJob.job_key > last_job_key)
                jobs = session.scalars(
                    job_query.order_by(CollectionSeedScanJob.job_key).limit(
                        SEED_SCAN_MAINTENANCE_BATCH_SIZE
                    )
                ).all()
                if not jobs:
                    break
                last_job_key = jobs[-1].job_key
                job_keys = [job.job_key for job in jobs]
                for job in jobs:
                    job.status = "pending"
                    job.completed_at = None
                    job.updated_at = now
                    session.add(job)
                session.flush()

                last_progress_key: str | None = None
                while job_keys:
                    progress_query = select(CollectionSeedScanProgress).where(
                        CollectionSeedScanProgress.job_key.in_(job_keys)
                    )
                    if last_progress_key is not None:
                        progress_query = progress_query.where(
                            CollectionSeedScanProgress.progress_key > last_progress_key
                        )
                    progress_rows = session.scalars(
                        progress_query.order_by(
                            CollectionSeedScanProgress.progress_key
                        ).limit(SEED_SCAN_MAINTENANCE_BATCH_SIZE)
                    ).all()
                    if not progress_rows:
                        break
                    last_progress_key = progress_rows[-1].progress_key
                    for progress in progress_rows:
                        progress.status = "pending"
                        progress.next_page = 1
                        progress.last_success_page = None
                        progress.completed_at = None
                        progress.leased_by = None
                        progress.lease_until = None
                        progress.retry_count = 0
                        progress.last_error = None
                        progress.updated_at = now
                        session.add(progress)
                    session.flush()
                    reset_progress += len(progress_rows)

                reset_jobs += len(jobs)
                # Keep each ORM window bounded while retaining one atomic transaction.
                session.expunge_all()
        return {
            "ok": True,
            "location_code": safe_location_code,
            "reset": {"jobs": reset_jobs, "progress": reset_progress},
        }
