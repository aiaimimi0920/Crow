"""Manual-review admission and staged work preserve queue-before-write ordering."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, cast

from .manual_review_write_contracts import (
    PreparedReviewWork,
    PrepareReview,
    Record,
    ReviewWriteHandler,
    ReviewWriteHost,
)


@dataclass(frozen=True)
class ReviewWriteHandlers:
    _post_manual_review_receipt: Callable[[ReviewWriteHandler], None]
    _prepare_manual_review_receipt_submission: PrepareReview
    __all__: ClassVar[list[str]] = [
        "_post_manual_review_receipt",
        "_prepare_manual_review_receipt_submission",
    ]


def bind_review_writes(host: ReviewWriteHost) -> ReviewWriteHandlers:
    def _post_manual_review_receipt(self: ReviewWriteHandler) -> None:
        from uuid import uuid4

        if not host._require_control_plane(self):
            return
        accepted, payload = host._read_json_body(self)
        if not accepted:
            return
        valid, error_payload = host._validate_manual_review_receipt_payload(
            payload if isinstance(payload, dict) else {}
        )
        if not valid:
            self.send_error_json(
                status=400,
                code=cast(str, error_payload["code"]),
                message=cast(str, error_payload["message"]),
                details=cast(Record, error_payload.get("details", {})),
            )
            return
        active_data_root = Path(getattr(host.AVM_SERVICE, "data_dir", host.DATA_DIR))
        try:
            mode = str(payload.get("mode", "sync") or "sync").lower()
            maintenance_job_id = uuid4().hex if mode == "async" else None
            work = host._prepare_manual_review_receipt_submission(
                active_data_root,
                payload,
                mode,
                maintenance_job_id=maintenance_job_id,
            )
        except Exception as error:  # noqa: BLE001 - preserve HTTP preparation boundary
            self.send_error_json(
                status=500,
                code="AVM_MANUAL_REVIEW_RECEIPT_UPSERT_FAILED",
                message="Unable to prepare manual review receipt",
                details={"error": str(error)},
            )
            return
        if mode == "sync":
            self._enqueue_collection_job(
                "manual_review_receipt",
                work,
                "AVM_MANUAL_REVIEW_RECEIPT_MAINTENANCE_FAILED",
            )
            return
        # Explicit async callers retain HTTP 200 while using the durable common queue.
        self._enqueue_collection_job(
            "manual_review_receipt",
            work,
            "AVM_MANUAL_REVIEW_RECEIPT_ASYNC_FAILED",
            job_id=maintenance_job_id,
            response_status=200,
            response_extra={
                **getattr(work, "preview", {}),
                "status": "ok",
                "execution_mode": "async",
                "maintenance_triggered": True,
                "maintenance_job_id": maintenance_job_id,
                "maintenance_job_status": "queued",
                "manual_review_control_plane_storage": host._manual_review_control_plane_storage(
                    active_data_root
                ),
                "manual_review_control_plane_backup": host._manual_review_control_plane_backup(
                    active_data_root
                ),
            },
        )

    def _prepare_manual_review_receipt_submission(
        active_data_root: Path,
        payload: Record,
        mode: str,
        *,
        maintenance_job_id: str | None = None,
    ) -> PreparedReviewWork:
        from copy import deepcopy

        from .collection_job_control import job_checkpoint
        from .collection_jobs import CollectionJobFailure

        receipt: Record = {
            "action": payload["action"],
            "ready_signal": payload["ready_signal"],
            "status": payload["status"],
            "payload": deepcopy(payload.get("payload") or {}),
        }
        for key in ("resolution_notes", "source"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                receipt[key] = value.strip()
        maintenance_options = host._normalize_manual_review_maintenance_options(
            payload.get("maintenance")
        )
        repository = host.DB_REPOSITORY if host.DB_REPOSITORY.enabled else None
        store_path = host._manual_review_receipt_store_path(active_data_root)
        operations_path = host._manual_review_receipt_operations_path(active_data_root)
        upsert = host.upsert_manual_review_receipt
        append_operation = host.append_manual_review_receipt_operation
        maintenance = host.run_recent_enrich_maintenance
        load_context = host._manual_review_receipt_context
        summaries = {
            "manual_review_receipt_jobs_summary": host._manual_review_receipt_jobs_summary,
            "manual_review_control_plane_storage": host._manual_review_control_plane_storage,
            "manual_review_control_plane_backup": host._manual_review_control_plane_backup,
            "manual_review_control_plane_backup_repairs_summary": host._manual_review_control_plane_backup_repairs_summary,
            "manual_review_control_plane_integrity": host._manual_review_control_plane_integrity,
            "manual_review_control_plane_integrity_history_summary": host._manual_review_control_plane_integrity_history_summary,
            "manual_review_control_plane_stability": host._manual_review_control_plane_stability,
            "manual_review_control_plane_guidance": host._manual_review_control_plane_guidance,
        }
        preview: Record = {
            "status": "ok",
            "operation": "created",
            "receipt": dict(receipt),
        }
        try:
            existing = host.list_manual_review_receipts(
                store_path, repository=repository
            )
            if any(
                str(item.get("action") or "").strip() == receipt["action"]
                and str(item.get("ready_signal") or "").strip()
                == receipt["ready_signal"]
                for item in existing.get("receipts") or []
            ):
                preview["operation"] = "updated"
        except Exception:  # noqa: BLE001, S110 - preview is advisory; worker reports errors
            # The durable worker remains authoritative; failed previews never write.
            pass
        failure_code = (
            "AVM_MANUAL_REVIEW_RECEIPT_SYNC_FINALIZE_FAILED"
            if mode == "sync"
            else "AVM_MANUAL_REVIEW_RECEIPT_ASYNC_FINALIZE_FAILED"
        )

        def run() -> Record:
            try:
                job_checkpoint()
                operation_result = upsert(store_path, receipt, repository=repository)
                context = load_context(active_data_root)
                response: Record = {
                    "status": "ok",
                    "operation": operation_result["operation"],
                    "execution_mode": mode,
                    "maintenance_triggered": False,
                    "receipt": operation_result["receipt"],
                    **{
                        key: context[key]
                        for key in (
                            *summaries,
                            "manual_review_receipt_summary",
                            "operator_overview",
                        )
                    },
                }
            except Exception as error:
                raise CollectionJobFailure(
                    "AVM_MANUAL_REVIEW_RECEIPT_UPSERT_FAILED"
                ) from error
            try:
                job_checkpoint()
                report = maintenance(
                    data_root=active_data_root,
                    repository=repository,
                    **maintenance_options,
                )
            except Exception as error:
                raise CollectionJobFailure(
                    "AVM_MANUAL_REVIEW_RECEIPT_MAINTENANCE_FAILED"
                ) from error
            try:
                job_checkpoint()
                operation_options: Record = {}
                response["maintenance_report"] = report
                for key in ("manual_review_receipt_summary", "operator_overview"):
                    response[key] = report.get(key, context[key])
                if maintenance_job_id:
                    operation_options["maintenance_job_id"] = maintenance_job_id
                    response["maintenance_job_id"] = maintenance_job_id
                    response["maintenance_job_status"] = "completed"
                append_operation(
                    operations_path,
                    operation=operation_result["operation"],
                    receipt=operation_result["receipt"],
                    execution_mode=mode,
                    repository=repository,
                    **operation_options,
                )
                response["maintenance_triggered"] = True
                response.update(
                    {key: reader(active_data_root) for key, reader in summaries.items()}
                )
            except Exception as error:
                raise CollectionJobFailure(failure_code) from error
            return response

        prepared = cast(PreparedReviewWork, run)
        prepared.preview = preview
        return prepared

    return ReviewWriteHandlers(
        _post_manual_review_receipt, _prepare_manual_review_receipt_submission
    )
