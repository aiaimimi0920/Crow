from __future__ import annotations

from typing import Any, Dict, Sequence
from uuid import uuid4

from sqlalchemy import and_, case, func, or_, select

from .models import (
    ManualReviewReceipt,
    ManualReviewReceiptJob,
    ManualReviewReceiptOperation,
    PropertyAudit,
    PropertyListing,
)
from .repository_context import _parse_dt


class RepositoryManualReviewJobsMixin:
    def _manual_review_receipt_job_payload_from_row(
        self, row: ManualReviewReceiptJob
    ) -> Dict[str, Any]:
        return {
            "job_id": row.job_id,
            "status": row.status,
            "receipt_key": {
                "action": row.receipt_action,
                "ready_signal": row.receipt_ready_signal,
            },
            "created_at": self._fmt_dt(row.created_at),
            "started_at": self._fmt_dt(row.started_at),
            "finished_at": self._fmt_dt(row.finished_at),
            "maintenance_options": dict(row.maintenance_options or {}),
            "result_summary": (
                dict(row.result_summary or {})
                if isinstance(row.result_summary, dict)
                else row.result_summary
            ),
            "error": row.error,
        }

    def create_manual_review_receipt_job(
        self, *, receipt_key: Dict[str, Any], maintenance_options: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {}
        self.initialize()
        row = ManualReviewReceiptJob(
            job_id=str(uuid4()),
            status="queued",
            receipt_action=str(receipt_key.get("action") or "").strip(),
            receipt_ready_signal=str(receipt_key.get("ready_signal") or "").strip(),
            maintenance_options=dict(maintenance_options or {}),
        )
        with self.session_factory.begin() as session:
            session.add(row)
        return self._manual_review_receipt_job_payload_from_row(row)

    def import_manual_review_receipt_jobs_snapshot(
        self, snapshot: Dict[str, Any]
    ) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        jobs: Sequence[Any] = (
            snapshot.get("jobs") if isinstance(snapshot, dict) else []  # type: ignore[assignment]
        )
        if not isinstance(jobs, list):
            return 0
        imported = 0
        with self.session_factory.begin() as session:
            for item in jobs:
                if not isinstance(item, dict):
                    continue
                job_id = str(item.get("job_id") or "").strip()
                receipt_key = (
                    item.get("receipt_key")
                    if isinstance(item.get("receipt_key"), dict)
                    else {}
                )
                receipt_action = str(receipt_key.get("action") or "").strip()
                receipt_ready_signal = str(
                    receipt_key.get("ready_signal") or ""
                ).strip()
                if not job_id or not receipt_action or not receipt_ready_signal:
                    continue
                row = session.get(ManualReviewReceiptJob, job_id) or ManualReviewReceiptJob(
                    job_id=job_id,
                    status=str(item.get("status") or "").strip() or "queued",
                    receipt_action=receipt_action,
                    receipt_ready_signal=receipt_ready_signal,
                )
                row.status = str(item.get("status") or "").strip() or row.status
                row.receipt_action = receipt_action
                row.receipt_ready_signal = receipt_ready_signal
                row.maintenance_options = dict(item.get("maintenance_options") or {})
                row.result_summary = (
                    dict(item.get("result_summary") or {})
                    if isinstance(item.get("result_summary"), dict)
                    else None
                )
                row.error = str(item.get("error") or "").strip() or None
                row.started_at = _parse_dt(item.get("started_at"))
                row.finished_at = _parse_dt(item.get("finished_at"))
                created_at = _parse_dt(item.get("created_at"))
                if created_at is not None:
                    row.created_at = created_at
                session.add(row)
                imported += 1
        return imported

    def update_manual_review_receipt_job(
        self, job_id: str, **fields: Any
    ) -> Dict[str, Any] | None:
        if not self.enabled:
            return None
        self.initialize()
        key = str(job_id or "").strip()
        with self.session_factory.begin() as session:
            row = session.get(ManualReviewReceiptJob, key)
            if row is None:
                return None
            if "status" in fields:
                row.status = str(fields.get("status") or "").strip() or row.status
            if "maintenance_options" in fields:
                row.maintenance_options = dict(fields.get("maintenance_options") or {})
            if "result_summary" in fields:
                result_summary = fields.get("result_summary")
                row.result_summary = (
                    dict(result_summary or {})
                    if isinstance(result_summary, dict)
                    else None
                )
            if "error" in fields:
                row.error = str(fields.get("error") or "").strip() or None
            if "started_at" in fields:
                row.started_at = _parse_dt(fields.get("started_at"))
            if "finished_at" in fields:
                row.finished_at = _parse_dt(fields.get("finished_at"))
        with self.session_factory() as session:
            row = session.get(ManualReviewReceiptJob, key)
            return (
                self._manual_review_receipt_job_payload_from_row(row)
                if row is not None
                else None
            )

    def get_manual_review_receipt_job(self, job_id: str) -> Dict[str, Any] | None:
        if not self.enabled:
            return None
        self.initialize()
        with self.session_factory() as session:
            row = session.get(ManualReviewReceiptJob, str(job_id or "").strip())
            return (
                self._manual_review_receipt_job_payload_from_row(row)
                if row is not None
                else None
            )

    def manual_review_receipt_jobs_snapshot(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"jobs": [], "queue": [], "running_job_id": None}
        self.initialize()
        with self.session_factory() as session:
            rows = list(
                session.execute(
                    select(ManualReviewReceiptJob).order_by(
                        ManualReviewReceiptJob.created_at.asc(),
                        ManualReviewReceiptJob.job_id.asc(),
                    )
                ).scalars()
            )
        jobs = [self._manual_review_receipt_job_payload_from_row(row) for row in rows]
        queue = [job["job_id"] for job in jobs if job.get("status") == "queued"]
        running_job = next(
            (job for job in jobs if job.get("status") == "running"), None
        )
        return {
            "jobs": jobs,
            "queue": queue,
            "running_job_id": running_job.get("job_id") if running_job else None,
        }

    def manual_review_control_plane_counts(self) -> Dict[str, int]:
        if not self.enabled:
            return {
                "receipt_count": 0,
                "job_count": 0,
                "operation_count": 0,
            }
        self.initialize()
        with self.session_factory() as session:
            return {
                "receipt_count": int(
                    session.scalar(select(func.count()).select_from(ManualReviewReceipt))
                    or 0
                ),
                "job_count": int(
                    session.scalar(
                        select(func.count()).select_from(ManualReviewReceiptJob)
                    )
                    or 0
                ),
                "operation_count": int(
                    session.scalar(
                        select(func.count()).select_from(ManualReviewReceiptOperation)
                    )
                    or 0
                ),
            }

    def stage_status_counts(self) -> Dict[str, int]:
        counts = {
            "seed_stored": 0,
            "detail_pending": 0,
            "detail_archived": 0,
            "detail_enriched": 0,
            "detail_blocked": 0,
            "detail_failed": 0,
            "detail_replay_requested": 0,
            "analysis_ready": 0,
            "analysis_not_ready": 0,
            "analysis_invalid": 0,
        }
        if not self.enabled:
            return counts
        self.initialize()
        active = PropertyListing.is_deleted.is_(False)
        with self.session_factory() as session:
            row = session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    and_(
                                        active,
                                        or_(
                                            PropertyAudit.seed_status == "stored",
                                            and_(
                                                PropertyAudit.seed_status.is_(None),
                                                PropertyListing.source_url.is_not(None),
                                                PropertyListing.source_url != "",
                                            ),
                                        ),
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(case((self._detail_pending_filter(), 1), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    and_(
                                        active,
                                        or_(
                                            PropertyAudit.detail_status == "archived",
                                            and_(
                                                PropertyAudit.detail_status.is_(None),
                                                PropertyAudit.detail_archive_path.is_not(
                                                    None
                                                ),
                                                PropertyAudit.detail_archive_path != "",
                                                or_(
                                                    PropertyAudit.detail_captured.is_(
                                                        False
                                                    ),
                                                    PropertyAudit.detail_captured.is_(
                                                        None
                                                    ),
                                                ),
                                            ),
                                        ),
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    and_(
                                        active,
                                        or_(
                                            PropertyAudit.detail_status == "enriched",
                                            and_(
                                                PropertyAudit.detail_status.is_(None),
                                                PropertyAudit.detail_captured.is_(True),
                                            ),
                                        ),
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    and_(
                                        active,
                                        or_(
                                            PropertyAudit.detail_status == "blocked",
                                            and_(
                                                PropertyAudit.detail_status.is_(None),
                                                PropertyAudit.detail_fetch_status.in_(
                                                    (
                                                        "login_redirect",
                                                        "anti_bot_gate",
                                                        "empty_html",
                                                    )
                                                ),
                                            ),
                                        ),
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    and_(
                                        active,
                                        or_(
                                            PropertyAudit.detail_status == "failed",
                                            and_(
                                                PropertyAudit.detail_status.is_(None),
                                                PropertyAudit.detail_fetch_status.in_(
                                                    (
                                                        "failed",
                                                        "fetch_failed",
                                                        "timeout",
                                                        "http_error",
                                                        "parse_error",
                                                    )
                                                ),
                                            ),
                                        ),
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    and_(
                                        active,
                                        PropertyAudit.detail_status
                                        == "replay_requested",
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(case((self._analysis_ready_filter(), 1), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    and_(
                                        active,
                                        PropertyAudit.analysis_status == "invalid",
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(func.sum(case((active, 1), else_=0)), 0),
                )
                .select_from(PropertyListing)
                .outerjoin(
                    PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id
                )
            ).one()
            counts["seed_stored"] = int(row[0] or 0)
            counts["detail_pending"] = int(row[1] or 0)
            counts["detail_archived"] = int(row[2] or 0)
            counts["detail_enriched"] = int(row[3] or 0)
            counts["detail_blocked"] = int(row[4] or 0)
            counts["detail_failed"] = int(row[5] or 0)
            counts["detail_replay_requested"] = int(row[6] or 0)
            counts["analysis_ready"] = int(row[7] or 0)
            counts["analysis_invalid"] = int(row[8] or 0)
            total_active = int(row[9] or 0)
            counts["analysis_not_ready"] = max(
                0, total_active - counts["analysis_ready"] - counts["analysis_invalid"]
            )
        return counts
