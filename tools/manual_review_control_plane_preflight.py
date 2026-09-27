"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.manual_review_control_plane_context import *

if TYPE_CHECKING:
    from src.storage.repository import PropertyRepository


def generate_manual_review_control_plane_rollout_preflight(
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
    source_json_counts = {
        "receipt_count": len(receipt_snapshot.get("receipts") or []),
        "job_count": len(job_snapshot.get("jobs") or []),
        "operation_count": len(operation_snapshot),
    }
    backup_files_present = {
        "receipts": (avm_root / "manual_review_receipts.json").exists(),
        "jobs": (avm_root / "manual_review_receipt_jobs.json").exists(),
        "operations": (avm_root / "manual_review_receipt_operations.jsonl").exists(),
    }

    recommended_next_steps: list[str] = []
    recommended_commands: list[str] = []

    if not repo.settings.url:
        preflight_status = "requires_database_configuration"
        recommended_next_steps = [
            "configure_database_repository",
            "run_alembic_upgrade_head",
            "rerun_rollout_preflight",
        ]
        recommended_commands = [
            "set FAPAI_DB_URL=<your-db-url>",
            "alembic upgrade head",
        ]
        return {
            "preflight_status": preflight_status,
            "repository_enabled": False,
            "repository_counts": {"receipt_count": 0, "job_count": 0, "operation_count": 0},
            "source_json_counts": source_json_counts,
            "backup_files_present": backup_files_present,
            "recommended_next_steps": recommended_next_steps,
            "recommended_commands": recommended_commands,
            "read_only": True,
        }

    if not repo.enabled:
        preflight_status = "repository_disabled_by_config"
        recommended_next_steps = [
            "enable_database_repository",
            "run_alembic_upgrade_head",
            "rerun_rollout_preflight",
        ]
        recommended_commands = [
            "set FAPAI_DB_ENABLED=1",
            "alembic upgrade head",
        ]
        return {
            "preflight_status": preflight_status,
            "repository_enabled": False,
            "repository_counts": {"receipt_count": 0, "job_count": 0, "operation_count": 0},
            "source_json_counts": source_json_counts,
            "backup_files_present": backup_files_present,
            "recommended_next_steps": recommended_next_steps,
            "recommended_commands": recommended_commands,
            "read_only": True,
        }

    repository_counts = repo.manual_review_control_plane_counts()
    counts_match = (
        repository_counts["receipt_count"] == source_json_counts["receipt_count"]
        and repository_counts["job_count"] == source_json_counts["job_count"]
        and repository_counts["operation_count"] == source_json_counts["operation_count"]
    )
    if any(repository_counts.values()):
        if all(backup_files_present.values()) and counts_match:
            preflight_status = "ready_for_runtime_validation"
            recommended_next_steps = [
                "verify_backend_status",
                "verify_release_gate",
                "exercise_control_plane_crud",
            ]
            recommended_commands = [
                'curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_status"',
                'curl "http://127.0.0.1:8001/api/analysis/release_gate"',
            ]
        else:
            preflight_status = "ready_for_backup_sync"
            recommended_next_steps = [
                "run_control_plane_backup_export",
                "verify_backend_status",
                "verify_backup_status",
            ]
            recommended_commands = [
                'python tools/export_manual_review_control_plane_to_json.py --data-root datas --db-url "<your-db-url>"',
                'curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_status"',
            ]
    else:
        if any(source_json_counts.values()):
            preflight_status = "ready_for_backfill"
            recommended_next_steps = [
                "run_control_plane_backfill",
                "verify_backend_status",
                "verify_backup_status",
            ]
            recommended_commands = [
                'python tools/backfill_manual_review_control_plane_to_db.py --data-root datas --db-url "<your-db-url>"',
                'curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_status"',
            ]
        else:
            preflight_status = "ready_for_clean_start"
            recommended_next_steps = [
                "run_alembic_upgrade_head",
                "start_control_plane_runtime",
                "verify_backend_status",
            ]
            recommended_commands = [
                "alembic upgrade head",
                'curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_status"',
            ]

    return {
        "preflight_status": preflight_status,
        "repository_enabled": True,
        "repository_counts": repository_counts,
        "source_json_counts": source_json_counts,
        "backup_files_present": backup_files_present,
        "recommended_next_steps": recommended_next_steps,
        "recommended_commands": recommended_commands,
        "read_only": True,
    }


__all__ = (
    'generate_manual_review_control_plane_rollout_preflight',
)
