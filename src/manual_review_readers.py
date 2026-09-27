"""Late-bound repository adapters for manual-review status readers."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from src import collection_stage_status as _COLLECTION_STAGE_STATUS
from src import manual_review_context as _MANUAL_REVIEW_CONTEXT
from src import manual_review_status as _MANUAL_REVIEW_STATUS
from src.storage.repository import PropertyRepository


@dataclass(frozen=True)
class ManualReviewReaders:
    repository: Callable[[], PropertyRepository]
    data_root: Callable[[], Path]

    __all__: ClassVar[tuple[str, ...]] = (
        "_db_collection_stage_snapshot",
        "_manual_review_receipt_jobs_snapshot",
        "_manual_review_receipt_jobs_summary",
        "_manual_review_receipt_operations_summary",
        "_manual_review_control_plane_storage",
        "_manual_review_control_plane_backup",
        "_manual_review_control_plane_integrity",
        "_manual_review_control_plane_stability",
        "_manual_review_control_plane_guidance",
        "_manual_review_control_plane_runtime_summary",
        "_load_manual_review_receipt_snapshot_for_runtime",
        "_manual_review_receipt_context",
    )

    def _db_collection_stage_snapshot(self):
        return _COLLECTION_STAGE_STATUS._db_collection_stage_snapshot(
            self.data_root(),
            repository=self.repository(),
        )

    def _manual_review_receipt_jobs_snapshot(self, data_root, collection_manager=None):
        return _MANUAL_REVIEW_STATUS._manual_review_receipt_jobs_snapshot(
            data_root,
            collection_manager,
            repository=self.repository(),
        )

    def _manual_review_receipt_jobs_summary(self, data_root):
        return _MANUAL_REVIEW_STATUS._manual_review_receipt_jobs_summary(
            data_root,
            repository=self.repository(),
        )

    def _manual_review_receipt_operations_summary(self, data_root):
        return _MANUAL_REVIEW_STATUS._manual_review_receipt_operations_summary(
            data_root,
            repository=self.repository(),
        )

    def _manual_review_control_plane_storage(self, data_root):
        return _MANUAL_REVIEW_STATUS._manual_review_control_plane_storage(
            data_root,
            repository=self.repository(),
        )

    def _manual_review_control_plane_backup(self, data_root):
        return _MANUAL_REVIEW_STATUS._manual_review_control_plane_backup(
            data_root,
            repository=self.repository(),
        )

    def _manual_review_control_plane_integrity(self, data_root):
        return _MANUAL_REVIEW_STATUS._manual_review_control_plane_integrity(
            data_root,
            repository=self.repository(),
        )

    def _manual_review_control_plane_stability(self, data_root):
        return _MANUAL_REVIEW_STATUS._manual_review_control_plane_stability(
            data_root,
            repository=self.repository(),
        )

    def _manual_review_control_plane_guidance(self, data_root):
        return _MANUAL_REVIEW_STATUS._manual_review_control_plane_guidance(
            data_root,
            repository=self.repository(),
        )

    def _manual_review_control_plane_runtime_summary(self, data_root):
        return _MANUAL_REVIEW_STATUS._manual_review_control_plane_runtime_summary(
            data_root,
            repository=self.repository(),
        )

    def _load_manual_review_receipt_snapshot_for_runtime(self, data_root):
        return _MANUAL_REVIEW_STATUS._load_manual_review_receipt_snapshot_for_runtime(
            data_root,
            repository=self.repository(),
        )

    def _manual_review_receipt_context(self, data_root):
        return _MANUAL_REVIEW_CONTEXT._manual_review_receipt_context(
            data_root,
            repository=self.repository(),
        )
