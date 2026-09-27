"""Explicit dependencies for queued manual-review receipt writes."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

Record = dict[str, object]


class PreparedReviewWork(Protocol):
    preview: Record

    def __call__(self) -> Record: ...


class PrepareReview(Protocol):
    def __call__(
        self,
        active_data_root: Path,
        payload: Record,
        mode: str,
        *,
        maintenance_job_id: str | None = None,
    ) -> PreparedReviewWork: ...


class ReviewWriteHandler(Protocol):
    def send_error_json(
        self, *, status: int, code: str, message: str, details: Record
    ) -> None: ...
    def _enqueue_collection_job(
        self,
        kind: str,
        work: Callable[[], Record],
        error_code: str,
        *,
        job_id: str | None = None,
        response_status: int = 202,
        response_extra: Record | None = None,
    ) -> object: ...


class ReviewWriteRepository(Protocol):
    enabled: bool


class ReviewWriteHost(Protocol):
    AVM_SERVICE: object
    DATA_DIR: str | Path
    DB_REPOSITORY: ReviewWriteRepository

    def _require_control_plane(self, handler: ReviewWriteHandler) -> bool: ...
    def _read_json_body(self, handler: ReviewWriteHandler) -> tuple[bool, Record]: ...
    def _validate_manual_review_receipt_payload(
        self, payload: Record
    ) -> tuple[bool, Record]: ...
    def _prepare_manual_review_receipt_submission(
        self,
        active_data_root: Path,
        payload: Record,
        mode: str,
        *,
        maintenance_job_id: str | None = None,
    ) -> PreparedReviewWork: ...
    def _normalize_manual_review_maintenance_options(
        self, options: object
    ) -> Record: ...
    def _manual_review_receipt_store_path(self, root: Path) -> Path: ...
    def _manual_review_receipt_operations_path(self, root: Path) -> Path: ...
    def list_manual_review_receipts(
        self, path: Path, *, repository: ReviewWriteRepository | None
    ) -> dict[str, list[Record]]: ...
    def upsert_manual_review_receipt(
        self, path: Path, receipt: Record, *, repository: ReviewWriteRepository | None
    ) -> Record: ...
    def append_manual_review_receipt_operation(
        self,
        path: Path,
        *,
        operation: object,
        receipt: object,
        execution_mode: str,
        repository: ReviewWriteRepository | None,
        **options: object,
    ) -> object: ...
    def run_recent_enrich_maintenance(
        self,
        *,
        data_root: Path,
        repository: ReviewWriteRepository | None,
        **options: object,
    ) -> Record: ...
    def _manual_review_receipt_context(self, root: Path) -> Record: ...
    def _manual_review_receipt_jobs_summary(self, root: Path) -> Record: ...
    def _manual_review_control_plane_storage(self, root: Path) -> Record: ...
    def _manual_review_control_plane_backup(self, root: Path) -> Record: ...
    def _manual_review_control_plane_backup_repairs_summary(
        self, root: Path
    ) -> Record: ...
    def _manual_review_control_plane_integrity(self, root: Path) -> Record: ...
    def _manual_review_control_plane_integrity_history_summary(
        self, root: Path
    ) -> Record: ...
    def _manual_review_control_plane_stability(self, root: Path) -> Record: ...
    def _manual_review_control_plane_guidance(self, root: Path) -> Record: ...
