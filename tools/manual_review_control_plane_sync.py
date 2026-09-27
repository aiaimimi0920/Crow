"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.manual_review_control_plane_context import *

if TYPE_CHECKING:
    from src.storage.repository import PropertyRepository


def backfill_manual_review_control_plane_to_db(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    avm_root = data_root / "avm"

    receipt_snapshot = _load_receipt_snapshot(avm_root / "manual_review_receipts.json")
    job_snapshot = _load_job_snapshot(avm_root / "manual_review_receipt_jobs.json")
    operation_snapshot = _load_operation_snapshot(avm_root / "manual_review_receipt_operations.jsonl")

    imported_receipts = repo.import_manual_review_receipt_snapshot(receipt_snapshot)
    imported_jobs = repo.import_manual_review_receipt_jobs_snapshot(job_snapshot)
    imported_operations = repo.import_manual_review_receipt_operations(operation_snapshot)

    return {
        "receipt_count": imported_receipts,
        "job_count": imported_jobs,
        "operation_count": imported_operations,
        "source_receipt_count": len(receipt_snapshot.get("receipts") or []),
        "source_job_count": len(job_snapshot.get("jobs") or []),
        "source_operation_count": len(operation_snapshot),
    }


def export_manual_review_control_plane_to_json(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    if not repo.enabled:
        return {
            "exported": False,
            "reason": "repository_disabled",
            "receipt_count": 0,
            "job_count": 0,
            "operation_count": 0,
        }

    avm_root = data_root / "avm"
    receipt_snapshot = repo.list_manual_review_receipts()
    job_snapshot = repo.manual_review_receipt_jobs_snapshot()
    operation_snapshot = repo.list_manual_review_receipt_operations()

    _write_json_payload(avm_root / "manual_review_receipts.json", receipt_snapshot)
    _write_json_payload(avm_root / "manual_review_receipt_jobs.json", job_snapshot)
    _write_jsonl_payload(avm_root / "manual_review_receipt_operations.jsonl", operation_snapshot)

    return {
        "exported": True,
        "reason": "repository_exported",
        "receipt_count": len(receipt_snapshot.get("receipts") or []),
        "job_count": len(job_snapshot.get("jobs") or []),
        "operation_count": len(operation_snapshot),
    }


def sync_manual_review_control_plane_json_backup(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    if not repo.enabled:
        return {
            "exported": False,
            "reason": "repository_disabled",
            "receipt_count": 0,
            "job_count": 0,
            "operation_count": 0,
        }
    return export_manual_review_control_plane_to_json(data_root, repository=repo)


def ensure_manual_review_control_plane_backup_synced(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    if not repo.enabled:
        return {
            "repaired": False,
            "reason": "repository_disabled",
            "receipt_count": 0,
            "job_count": 0,
            "operation_count": 0,
        }

    ensure_manual_review_control_plane_backfilled(data_root, repository=repo)
    avm_root = data_root / "avm"
    receipt_path = avm_root / "manual_review_receipts.json"
    jobs_path = avm_root / "manual_review_receipt_jobs.json"
    operations_path = avm_root / "manual_review_receipt_operations.jsonl"
    files_present = {
        "receipts": receipt_path.exists(),
        "jobs": jobs_path.exists(),
        "operations": operations_path.exists(),
    }
    source_counts = repo.manual_review_control_plane_counts()
    backup_counts = {
        "receipt_count": len(_load_receipt_snapshot(receipt_path).get("receipts") or []),
        "job_count": len(_load_job_snapshot(jobs_path).get("jobs") or []),
        "operation_count": len(_load_operation_snapshot(operations_path)),
    }
    counts_match = (
        source_counts["receipt_count"] == backup_counts["receipt_count"]
        and source_counts["job_count"] == backup_counts["job_count"]
        and source_counts["operation_count"] == backup_counts["operation_count"]
    )
    if all(files_present.values()) and counts_match:
        return {
            "repaired": False,
            "reason": "already_in_sync",
            **source_counts,
        }

    reason = "repaired_missing_backup" if not all(files_present.values()) else "repaired_count_mismatch"
    _append_manual_review_control_plane_backup_repair(
        data_root,
        reason=reason,
        source_counts=source_counts,
        backup_counts_before=backup_counts,
    )
    export = sync_manual_review_control_plane_json_backup(data_root, repository=repo)
    return {
        "repaired": True,
        "reason": reason,
        "receipt_count": int(export.get("receipt_count", 0) or 0),
        "job_count": int(export.get("job_count", 0) or 0),
        "operation_count": int(export.get("operation_count", 0) or 0),
    }


def ensure_manual_review_control_plane_backfilled(
    data_root: Path,
    *,
    db_url: str | None = None,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    repo = _build_repo(db_url, repository=repository)
    if not repo.enabled:
        return {
            "bootstrapped": False,
            "reason": "repository_disabled",
            "existing_counts": {"receipt_count": 0, "job_count": 0, "operation_count": 0},
        }

    counts = repo.manual_review_control_plane_counts()
    if any(counts.values()):
        return {
            "bootstrapped": False,
            "reason": "repository_not_empty",
            "existing_counts": counts,
        }

    preview = backfill_manual_review_control_plane_to_db(data_root, repository=repo)
    bootstrapped = any(
        int(preview.get(key, 0) or 0) > 0
        for key in ("receipt_count", "job_count", "operation_count")
    )
    return {
        "bootstrapped": bootstrapped,
        "reason": "imported" if bootstrapped else "source_empty",
        "existing_counts": counts,
        **preview,
    }


__all__ = (
    'backfill_manual_review_control_plane_to_db',
    'export_manual_review_control_plane_to_json',
    'sync_manual_review_control_plane_json_backup',
    'ensure_manual_review_control_plane_backup_synced',
    'ensure_manual_review_control_plane_backfilled',
)
