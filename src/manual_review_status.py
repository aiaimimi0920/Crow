from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from tools.analysis_stage_snapshots import load_manual_review_receipt_snapshot
from tools.backfill_manual_review_control_plane_to_db import (
    describe_manual_review_control_plane_backup,
    describe_manual_review_control_plane_storage,
    load_manual_review_control_plane_backup_repairs,
    load_manual_review_control_plane_integrity_history,
    record_manual_review_control_plane_integrity,
    summarize_manual_review_control_plane_backup_repairs,
    summarize_manual_review_control_plane_guidance,
    summarize_manual_review_control_plane_integrity,
    summarize_manual_review_control_plane_integrity_history,
    summarize_manual_review_control_plane_stability,
)
from tools.manual_review_receipt_audit import (
    load_manual_review_receipt_operations,
    summarize_manual_review_receipt_operations_snapshot,
)
from tools.manual_review_receipt_jobs import (
    load_manual_review_receipt_jobs,
    summarize_manual_review_receipt_jobs_snapshot,
)

if TYPE_CHECKING:
    from src.collection_jobs import CollectionJobManager
    from src.storage.repository import PropertyRepository


def _manual_review_receipt_store_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_receipts.json"


def _manual_review_receipt_operations_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_receipt_operations.jsonl"


def _manual_review_receipt_jobs_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_receipt_jobs.json"


def _manual_review_receipt_jobs_snapshot(
    data_root: Path,
    collection_manager: CollectionJobManager | None = None,
    *,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    from src.manual_review_job_view import merge_job_snapshot, persisted_receipts

    legacy = (
        repository.manual_review_receipt_jobs_snapshot()
        if repository is not None and repository.enabled
        else load_manual_review_receipt_jobs(
            _manual_review_receipt_jobs_path(data_root)
        )
    )
    receipts = (
        collection_manager.list(operation="manual_review_receipt")
        if collection_manager is not None
        else persisted_receipts(data_root)
    )
    return cast(dict[str, Any], merge_job_snapshot(legacy, receipts))


def _manual_review_receipt_jobs_summary(
    data_root: Path, *, repository: PropertyRepository | None = None
) -> dict[str, Any]:
    snapshot = _manual_review_receipt_jobs_snapshot(data_root, repository=repository)
    return cast(dict[str, Any], summarize_manual_review_receipt_jobs_snapshot(snapshot))


def _manual_review_receipt_operations_summary(
    data_root: Path, *, repository: PropertyRepository | None = None
) -> dict[str, Any]:
    operations = load_manual_review_receipt_operations(
        _manual_review_receipt_operations_path(data_root),
        limit=200,
        repository=repository
        if repository is not None and repository.enabled
        else None,
    )
    return cast(
        dict[str, Any], summarize_manual_review_receipt_operations_snapshot(operations)
    )


def _manual_review_control_plane_storage(
    data_root: Path, *, repository: PropertyRepository | None = None
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        describe_manual_review_control_plane_storage(
            data_root,
            repository=repository
            if repository is not None and repository.enabled
            else None,
        ),
    )


def _manual_review_control_plane_backup(
    data_root: Path, *, repository: PropertyRepository | None = None
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        describe_manual_review_control_plane_backup(
            data_root,
            repository=repository
            if repository is not None and repository.enabled
            else None,
        ),
    )


def _manual_review_control_plane_backup_repairs_summary(
    data_root: Path,
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        summarize_manual_review_control_plane_backup_repairs(
            load_manual_review_control_plane_backup_repairs(data_root)
        ),
    )


def _manual_review_control_plane_integrity(
    data_root: Path, *, repository: PropertyRepository | None = None
) -> dict[str, Any]:
    integrity = summarize_manual_review_control_plane_integrity(
        _manual_review_control_plane_storage(data_root, repository=repository),
        _manual_review_control_plane_backup(data_root, repository=repository),
        _manual_review_control_plane_backup_repairs_summary(data_root),
    )
    record_manual_review_control_plane_integrity(data_root, integrity)
    return cast(dict[str, Any], integrity)


def _manual_review_control_plane_integrity_history_summary(
    data_root: Path,
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        summarize_manual_review_control_plane_integrity_history(
            load_manual_review_control_plane_integrity_history(data_root)
        ),
    )


def _manual_review_control_plane_stability(
    data_root: Path, *, repository: PropertyRepository | None = None
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        summarize_manual_review_control_plane_stability(
            _manual_review_control_plane_integrity(data_root, repository=repository),
            _manual_review_control_plane_integrity_history_summary(data_root),
        ),
    )


def _manual_review_control_plane_guidance(
    data_root: Path, *, repository: PropertyRepository | None = None
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        summarize_manual_review_control_plane_guidance(
            _manual_review_control_plane_integrity(data_root, repository=repository),
            _manual_review_control_plane_stability(data_root, repository=repository),
            _manual_review_control_plane_backup_repairs_summary(data_root),
        ),
    )


def _manual_review_control_plane_runtime_summary(
    data_root: Path, *, repository: PropertyRepository | None = None
) -> dict[str, Any]:
    storage = describe_manual_review_control_plane_storage(
        data_root,
        repository=repository
        if repository is not None and repository.enabled
        else None,
    )
    backup = describe_manual_review_control_plane_backup(
        data_root,
        repository=repository
        if repository is not None and repository.enabled
        else None,
    )
    repairs_summary = summarize_manual_review_control_plane_backup_repairs(
        load_manual_review_control_plane_backup_repairs(data_root)
    )
    integrity = summarize_manual_review_control_plane_integrity(
        storage,
        backup,
        repairs_summary,
    )
    record_manual_review_control_plane_integrity(data_root, integrity)
    integrity_history_summary = summarize_manual_review_control_plane_integrity_history(
        load_manual_review_control_plane_integrity_history(data_root)
    )
    stability = summarize_manual_review_control_plane_stability(
        integrity,
        integrity_history_summary,
    )
    guidance = summarize_manual_review_control_plane_guidance(
        integrity,
        stability,
        repairs_summary,
    )
    return {
        "manual_review_control_plane_storage": storage,
        "manual_review_control_plane_backup": backup,
        "manual_review_control_plane_backup_repairs_summary": repairs_summary,
        "manual_review_control_plane_integrity": integrity,
        "manual_review_control_plane_integrity_history_summary": integrity_history_summary,
        "manual_review_control_plane_stability": stability,
        "manual_review_control_plane_guidance": guidance,
    }


def _load_manual_review_receipt_snapshot_for_runtime(
    data_root: Path, *, repository: PropertyRepository | None = None
) -> dict[str, Any]:
    receipt_path = data_root / "avm" / "manual_review_receipts.json"
    return cast(
        dict[str, Any],
        load_manual_review_receipt_snapshot(
            receipt_path,
            repository=repository
            if repository is not None and repository.enabled
            else None,
        ),
    )
