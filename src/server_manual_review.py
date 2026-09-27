from __future__ import annotations

from src.collection_stage_status import _db_collection_stage_snapshot
from src.manual_review_status import (
    _manual_review_control_plane_backup,
    _manual_review_control_plane_backup_repairs_summary,
    _manual_review_control_plane_integrity,
    _manual_review_control_plane_storage,
    _manual_review_receipt_jobs_path,
    _manual_review_receipt_jobs_snapshot,
    _manual_review_receipt_jobs_summary,
    _manual_review_receipt_operations_path,
    _manual_review_receipt_operations_summary,
    _manual_review_receipt_store_path,
)
from src.manual_review_validation import _normalize_manual_review_maintenance_options

MANUAL_REVIEW_RECEIPT_ENDPOINTS = (
    "/api/avm/manual_review_receipts",
    "/api/analysis/manual_review_receipts",
)

MANUAL_REVIEW_RECEIPT_JOB_ENDPOINTS = (
    "/api/avm/manual_review_receipt_jobs",
    "/api/analysis/manual_review_receipt_jobs",
)

MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS = (
    "/api/avm/manual_review_receipt_operations",
    "/api/analysis/manual_review_receipt_operations",
)

MANUAL_REVIEW_CONTROL_PLANE_STATUS_ENDPOINTS = (
    "/api/avm/manual_review_control_plane_status",
    "/api/analysis/manual_review_control_plane_status",
)

MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS = (
    "/api/avm/manual_review_control_plane_backup_repairs",
    "/api/analysis/manual_review_control_plane_backup_repairs",
)

MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS = (
    "/api/avm/manual_review_control_plane_integrity_history",
    "/api/analysis/manual_review_control_plane_integrity_history",
)

MANUAL_REVIEW_GET_GROUPS = {
    "_get_manual_review_receipts": tuple(MANUAL_REVIEW_RECEIPT_ENDPOINTS),
    "_get_manual_review_jobs": tuple(MANUAL_REVIEW_RECEIPT_JOB_ENDPOINTS),
    "_get_manual_review_operations": tuple(MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS),
    "_get_manual_review_control_status": tuple(
        MANUAL_REVIEW_CONTROL_PLANE_STATUS_ENDPOINTS
    ),
    "_get_manual_review_backup_repairs": tuple(
        MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS
    ),
    "_get_manual_review_integrity_history": tuple(
        MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS
    ),
}

__all__ = [
    "MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS",
    "MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS",
    "MANUAL_REVIEW_CONTROL_PLANE_STATUS_ENDPOINTS",
    "MANUAL_REVIEW_GET_GROUPS",
    "MANUAL_REVIEW_RECEIPT_ENDPOINTS",
    "MANUAL_REVIEW_RECEIPT_JOB_ENDPOINTS",
    "MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS",
    "_db_collection_stage_snapshot",
    "_manual_review_control_plane_backup",
    "_manual_review_control_plane_backup_repairs_summary",
    "_manual_review_control_plane_integrity",
    "_manual_review_control_plane_storage",
    "_manual_review_receipt_jobs_path",
    "_manual_review_receipt_jobs_snapshot",
    "_manual_review_receipt_jobs_summary",
    "_manual_review_receipt_operations_path",
    "_manual_review_receipt_operations_summary",
    "_manual_review_receipt_store_path",
    "_normalize_manual_review_maintenance_options",
]
