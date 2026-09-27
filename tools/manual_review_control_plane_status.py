"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.manual_review_control_plane_context import *

if TYPE_CHECKING:
    from src.storage.repository import PropertyRepository


def describe_manual_review_control_plane_storage(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    if repo.enabled:
        bootstrap = ensure_manual_review_control_plane_backfilled(data_root, repository=repo)
        counts = repo.manual_review_control_plane_counts()
        return {
            "repository_enabled": True,
            "state_source": "repository",
            "bootstrap_reason": bootstrap.get("reason"),
            "receipt_count": counts["receipt_count"],
            "job_count": counts["job_count"],
            "operation_count": counts["operation_count"],
        }

    receipt_snapshot = _load_receipt_snapshot(data_root / "avm" / "manual_review_receipts.json")
    job_snapshot = _load_job_snapshot(data_root / "avm" / "manual_review_receipt_jobs.json")
    operation_snapshot = _load_operation_snapshot(data_root / "avm" / "manual_review_receipt_operations.jsonl")
    return {
        "repository_enabled": False,
        "state_source": "json_fallback",
        "bootstrap_reason": "repository_disabled",
        "receipt_count": len(receipt_snapshot.get("receipts") or []),
        "job_count": len(job_snapshot.get("jobs") or []),
        "operation_count": len(operation_snapshot),
    }


def describe_manual_review_control_plane_backup(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    avm_root = data_root / "avm"
    receipt_path = avm_root / "manual_review_receipts.json"
    jobs_path = avm_root / "manual_review_receipt_jobs.json"
    operations_path = avm_root / "manual_review_receipt_operations.jsonl"

    receipt_snapshot = _load_receipt_snapshot(receipt_path)
    job_snapshot = _load_job_snapshot(jobs_path)
    operation_snapshot = _load_operation_snapshot(operations_path)
    backup_counts = {
        "backup_receipt_count": len(receipt_snapshot.get("receipts") or []),
        "backup_job_count": len(job_snapshot.get("jobs") or []),
        "backup_operation_count": len(operation_snapshot),
    }
    files_present = {
        "receipts": receipt_path.exists(),
        "jobs": jobs_path.exists(),
        "operations": operations_path.exists(),
    }

    if not repo.enabled:
        return {
            "repository_enabled": False,
            "backup_state": "runtime_json",
            "backup_reason": "repository_disabled",
            "source_receipt_count": backup_counts["backup_receipt_count"],
            "source_job_count": backup_counts["backup_job_count"],
            "source_operation_count": backup_counts["backup_operation_count"],
            "all_backup_files_present": all(files_present.values()),
            "backup_files_present": files_present,
            **backup_counts,
        }

    repair = ensure_manual_review_control_plane_backup_synced(data_root, repository=repo)
    receipt_snapshot = _load_receipt_snapshot(receipt_path)
    job_snapshot = _load_job_snapshot(jobs_path)
    operation_snapshot = _load_operation_snapshot(operations_path)
    backup_counts = {
        "backup_receipt_count": len(receipt_snapshot.get("receipts") or []),
        "backup_job_count": len(job_snapshot.get("jobs") or []),
        "backup_operation_count": len(operation_snapshot),
    }
    files_present = {
        "receipts": receipt_path.exists(),
        "jobs": jobs_path.exists(),
        "operations": operations_path.exists(),
    }
    source_counts = repo.manual_review_control_plane_counts()
    counts_match = (
        source_counts["receipt_count"] == backup_counts["backup_receipt_count"]
        and source_counts["job_count"] == backup_counts["backup_job_count"]
        and source_counts["operation_count"] == backup_counts["backup_operation_count"]
    )
    if all(files_present.values()) and counts_match:
        backup_state = "in_sync"
    elif not any(files_present.values()):
        backup_state = "missing_backup"
    else:
        backup_state = "count_mismatch"
    return {
        "repository_enabled": True,
        "backup_state": backup_state,
        "backup_reason": repair.get("reason"),
        "source_receipt_count": source_counts["receipt_count"],
        "source_job_count": source_counts["job_count"],
        "source_operation_count": source_counts["operation_count"],
        "all_backup_files_present": all(files_present.values()),
        "backup_files_present": files_present,
        **backup_counts,
    }


__all__ = (
    'describe_manual_review_control_plane_storage',
    'describe_manual_review_control_plane_backup',
)
