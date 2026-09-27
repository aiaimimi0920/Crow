"""Manual-review receipt, job and control-plane history HTTP reads."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol, TypedDict

Query = dict[str, list[str]]
Record = dict[str, object]


class JobSnapshot(TypedDict, total=False):
    jobs: list[Record]
    running_job_id: object


class ReviewReadServer(Protocol):
    def collection_jobs(self, root: Path) -> object: ...


class ReviewReadHandler(Protocol):
    server: ReviewReadServer

    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: Record
    ) -> None: ...


class ReviewRepository(Protocol):
    enabled: bool


class ReviewReadHost(Protocol):
    AVM_SERVICE: object
    DATA_DIR: str | Path
    DB_REPOSITORY: ReviewRepository

    def _manual_review_receipt_store_path(self, root: Path) -> Path: ...
    def _manual_review_receipt_operations_path(self, root: Path) -> Path: ...
    def list_manual_review_receipts(
        self, path: Path, *, repository: ReviewRepository | None
    ) -> dict[str, list[object]]: ...
    def _manual_review_control_plane_runtime_summary(self, root: Path) -> Record: ...
    def _manual_review_receipt_jobs_snapshot(
        self, root: Path, manager: object
    ) -> JobSnapshot: ...
    def _manual_review_receipt_context(self, root: Path) -> Record: ...
    def load_manual_review_receipt_operations(
        self, path: Path, *, repository: ReviewRepository | None
    ) -> list[Record]: ...
    def filter_manual_review_receipt_operations(
        self,
        operations: list[Record],
        *,
        action: str | None,
        ready_signal: str | None,
        limit: int,
    ) -> list[Record]: ...
    def load_manual_review_control_plane_backup_repairs(
        self, root: Path
    ) -> list[Record]: ...
    def load_manual_review_control_plane_integrity_history(
        self, root: Path
    ) -> list[Record]: ...


GetHandler = Callable[[ReviewReadHandler, object, str, Query], None]


@dataclass(frozen=True)
class ReviewReadHandlers:
    _get_manual_review_receipts: GetHandler
    _get_manual_review_jobs: GetHandler
    _get_manual_review_operations: GetHandler
    _get_manual_review_control_status: GetHandler
    _get_manual_review_backup_repairs: GetHandler
    _get_manual_review_integrity_history: GetHandler
    __all__: ClassVar[list[str]] = [
        "_get_manual_review_receipts",
        "_get_manual_review_jobs",
        "_get_manual_review_operations",
        "_get_manual_review_control_status",
        "_get_manual_review_backup_repairs",
        "_get_manual_review_integrity_history",
    ]


def bind_review_reads(host: ReviewReadHost) -> ReviewReadHandlers:
    def _get_manual_review_receipts(
        handler: ReviewReadHandler, parsed: object, request_path: str, query: Query
    ) -> None:
        try:
            root = Path(getattr(host.AVM_SERVICE, "data_dir", host.DATA_DIR))
            payload = host.list_manual_review_receipts(
                host._manual_review_receipt_store_path(root),
                repository=host.DB_REPOSITORY if host.DB_REPOSITORY.enabled else None,
            )
            runtime = host._manual_review_control_plane_runtime_summary(root)
            handler.send_json(
                {
                    "receipt_count": len(payload.get("receipts") or []),
                    "receipts": list(payload.get("receipts") or []),
                    **runtime,
                }
            )
        except Exception as e:  # noqa: BLE001 - preserve HTTP read boundary
            handler.send_error_json(
                status=500,
                code="AVM_MANUAL_REVIEW_RECEIPTS_READ_FAILED",
                message="manual review receipts 读取失败",
                details={"error": str(e)},
            )

    def _get_manual_review_jobs(
        handler: ReviewReadHandler, parsed: object, request_path: str, query: Query
    ) -> None:
        try:
            root = Path(getattr(host.AVM_SERVICE, "data_dir", host.DATA_DIR))
            manager = handler.server.collection_jobs(root)
            snapshot = host._manual_review_receipt_jobs_snapshot(root, manager)
            jobs = list(snapshot.get("jobs") or [])
            running = next(
                (
                    dict(job)
                    for job in jobs
                    if job.get("job_id") == snapshot.get("running_job_id")
                ),
                None,
            )
            queued = [dict(job) for job in jobs if job.get("status") == "queued"]
            runtime = host._manual_review_control_plane_runtime_summary(root)
            job_id = str((query.get("job_id") or [""])[0] or "").strip()
            if job_id:
                job = next((job for job in jobs if job.get("job_id") == job_id), None)
                context = host._manual_review_receipt_context(root)
                handler.send_json(
                    {
                        "job_count": len(jobs),
                        "job": job,
                        "running_job": running,
                        "queued_jobs": queued,
                        "manual_review_receipt_summary": context[
                            "manual_review_receipt_summary"
                        ],
                        "operator_overview": context["operator_overview"],
                        **runtime,
                    }
                )
            else:
                handler.send_json(
                    {
                        "job_count": len(jobs),
                        "jobs": jobs,
                        "running_job": running,
                        "queued_jobs": queued,
                        **runtime,
                    }
                )
        except Exception as e:  # noqa: BLE001 - preserve HTTP read boundary
            handler.send_error_json(
                status=500,
                code="AVM_MANUAL_REVIEW_RECEIPT_JOBS_READ_FAILED",
                message="manual review receipt jobs 读取失败",
                details={"error": str(e)},
            )

    def _get_manual_review_operations(
        handler: ReviewReadHandler, parsed: object, request_path: str, query: Query
    ) -> None:
        try:
            root = Path(getattr(host.AVM_SERVICE, "data_dir", host.DATA_DIR))
            action = str((query.get("action") or [""])[0] or "").strip() or None
            ready_signal = (
                str((query.get("ready_signal") or [""])[0] or "").strip() or None
            )
            try:
                limit = int((query.get("limit") or ["50"])[0] or 50)
            except (TypeError, ValueError):
                limit = 50
            if limit < 0:  # noqa: PLR1730 - keep route validation explicit
                limit = 0
            operations = host.filter_manual_review_receipt_operations(
                host.load_manual_review_receipt_operations(
                    host._manual_review_receipt_operations_path(root),
                    repository=host.DB_REPOSITORY
                    if host.DB_REPOSITORY.enabled
                    else None,
                ),
                action=action,
                ready_signal=ready_signal,
                limit=limit,
            )
            operations = list(reversed(operations))
            runtime = host._manual_review_control_plane_runtime_summary(root)
            handler.send_json(
                {
                    "operation_count": len(operations),
                    "operations": operations,
                    "applied_filters": {
                        "action": action,
                        "ready_signal": ready_signal,
                        "limit": limit,
                    },
                    **runtime,
                }
            )
        except Exception as e:  # noqa: BLE001 - preserve HTTP read boundary
            handler.send_error_json(
                status=500,
                code="AVM_MANUAL_REVIEW_RECEIPT_OPERATIONS_READ_FAILED",
                message="manual review receipt operations 读取失败",
                details={"error": str(e)},
            )

    def _get_manual_review_control_status(
        handler: ReviewReadHandler, parsed: object, request_path: str, query: Query
    ) -> None:
        try:
            root = Path(getattr(host.AVM_SERVICE, "data_dir", host.DATA_DIR))
            context = host._manual_review_receipt_context(root)
            handler.send_json(
                {
                    key: context[key]
                    for key in (
                        "manual_review_receipt_summary",
                        "manual_review_receipt_jobs_summary",
                        "manual_review_receipt_operations_summary",
                        "manual_review_control_plane_storage",
                        "manual_review_control_plane_backup",
                        "manual_review_control_plane_backup_repairs_summary",
                        "manual_review_control_plane_integrity",
                        "manual_review_control_plane_integrity_history_summary",
                        "manual_review_control_plane_stability",
                        "manual_review_control_plane_guidance",
                    )
                }
            )
        except Exception as e:  # noqa: BLE001 - preserve HTTP read boundary
            handler.send_error_json(
                status=500,
                code="AVM_MANUAL_REVIEW_CONTROL_PLANE_STATUS_FAILED",
                message="manual review control plane 状态读取失败",
                details={"error": str(e)},
            )

    def _get_manual_review_backup_repairs(
        handler: ReviewReadHandler, parsed: object, request_path: str, query: Query
    ) -> None:
        try:
            root = Path(getattr(host.AVM_SERVICE, "data_dir", host.DATA_DIR))
            try:
                limit = int((query.get("limit") or ["50"])[0] or 50)
            except (TypeError, ValueError):
                limit = 50
            if limit < 0:  # noqa: PLR1730 - keep route validation explicit
                limit = 0
            repairs = host.load_manual_review_control_plane_backup_repairs(root)
            repairs = [] if limit == 0 else repairs[-limit:]
            repairs = list(reversed(repairs))
            runtime = host._manual_review_control_plane_runtime_summary(root)
            handler.send_json(
                {
                    "repair_count": len(repairs),
                    "repairs": repairs,
                    "applied_filters": {"limit": limit},
                    **runtime,
                }
            )
        except Exception as e:  # noqa: BLE001 - preserve HTTP read boundary
            handler.send_error_json(
                status=500,
                code="AVM_MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIRS_FAILED",
                message="manual review control plane backup repairs 读取失败",
                details={"error": str(e)},
            )

    def _get_manual_review_integrity_history(
        handler: ReviewReadHandler, parsed: object, request_path: str, query: Query
    ) -> None:
        try:
            root = Path(getattr(host.AVM_SERVICE, "data_dir", host.DATA_DIR))
            try:
                limit = int((query.get("limit") or ["50"])[0] or 50)
            except (TypeError, ValueError):
                limit = 50
            if limit < 0:  # noqa: PLR1730 - keep route validation explicit
                limit = 0
            history = host.load_manual_review_control_plane_integrity_history(root)
            history = [] if limit == 0 else history[-limit:]
            history = list(reversed(history))
            runtime = host._manual_review_control_plane_runtime_summary(root)
            handler.send_json(
                {
                    "transition_count": len(history),
                    "history": history,
                    "applied_filters": {"limit": limit},
                    **runtime,
                }
            )
        except Exception as e:  # noqa: BLE001 - preserve HTTP read boundary
            handler.send_error_json(
                status=500,
                code="AVM_MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_FAILED",
                message="manual review control plane integrity history 读取失败",
                details={"error": str(e)},
            )

    return ReviewReadHandlers(
        _get_manual_review_receipts,
        _get_manual_review_jobs,
        _get_manual_review_operations,
        _get_manual_review_control_status,
        _get_manual_review_backup_repairs,
        _get_manual_review_integrity_history,
    )
