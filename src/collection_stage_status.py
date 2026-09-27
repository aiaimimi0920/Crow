"""Assemble collection status with explicit data and repository ownership."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.hybrid_collection_status import _hybrid_collection_status
from src.manual_review_status import (
    _load_manual_review_receipt_snapshot_for_runtime,
    _manual_review_control_plane_runtime_summary,
    _manual_review_receipt_jobs_summary,
    _manual_review_receipt_operations_summary,
)
from tools.analysis_stage_planner import (
    load_action_effectiveness_snapshot,
    load_optimization_loop_progress_snapshot,
    load_recent_gap_audit_snapshot,
    recommend_analysis_stage_actions,
    summarize_action_effectiveness_snapshot,
    summarize_manual_review_backlog,
    summarize_manual_review_receipt_snapshot,
    summarize_manual_review_reentry_application_summary,
    summarize_operator_action_surface,
    summarize_operator_overview,
    summarize_recoverability_snapshot,
    summarize_scheduler_feedback_snapshot,
)

if TYPE_CHECKING:
    from src.storage.repository import PropertyRepository


def _db_collection_stage_snapshot(
    data_root: Path,
    *,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    action_effectiveness = load_action_effectiveness_snapshot(
        data_root / "avm" / "data_supply_optimization_loop.json"
    )
    scheduler_progress = load_optimization_loop_progress_snapshot(
        data_root / "avm" / "data_supply_optimization_loop.json"
    )
    action_effectiveness_summary = summarize_action_effectiveness_snapshot(
        action_effectiveness
    )
    scheduler_feedback_summary = summarize_scheduler_feedback_snapshot(
        scheduler_progress
    )
    recent_gap_report = load_recent_gap_audit_snapshot(
        data_root / "avm" / "recent_gap_audit.json"
    )
    recoverability_summary = summarize_recoverability_snapshot(recent_gap_report)
    manual_review_backlog_summary = summarize_manual_review_backlog(recent_gap_report)
    manual_review_receipt_summary = summarize_manual_review_receipt_snapshot(
        _load_manual_review_receipt_snapshot_for_runtime(
            data_root, repository=repository
        ),
        manual_review_backlog_summary,
    )
    default_manual_review_reentry_application_summary = (
        summarize_manual_review_reentry_application_summary(
            manual_review_receipt_summary,
            {},
            recent_gap_report,
            recent_gap_report,
            {"analysis_blockers": {}},
            {"analysis_blockers": {}},
        )
    )
    default_recommended_actions = recommend_analysis_stage_actions(
        {"analysis_blockers": {}},
        gap_report=recent_gap_report,
        action_effectiveness=action_effectiveness,
        manual_review_receipt_summary=manual_review_receipt_summary,
    )
    default_operator_action_summary = summarize_operator_action_surface(
        default_recommended_actions,
        action_effectiveness_summary,
        recoverability_summary,
    )
    default_operator_action_summary["manual_review_backlog_summary"] = (
        manual_review_backlog_summary
    )
    default_operator_action_summary["manual_review_receipt_summary"] = (
        manual_review_receipt_summary
    )
    default_operator_action_summary["manual_review_reentry_application_summary"] = (
        default_manual_review_reentry_application_summary
    )
    hybrid_summaries, hybrid_overview = _hybrid_collection_status(data_root)
    default_operator_overview = summarize_operator_overview(
        default_operator_action_summary,
        scheduler_feedback_summary,
    )
    default_operator_overview.update(hybrid_overview)
    manual_review_receipt_jobs_summary = _manual_review_receipt_jobs_summary(
        data_root, repository=repository
    )
    manual_review_receipt_operations_summary = (
        _manual_review_receipt_operations_summary(data_root, repository=repository)
    )
    control_plane_runtime = _manual_review_control_plane_runtime_summary(
        data_root, repository=repository
    )
    if repository is None or not repository.enabled:
        return {
            "seed_stage": {},
            "detail_stage": {},
            "analysis_stage": {},
            "analysis_blockers": {},
            "recommended_actions": default_recommended_actions,
            "action_effectiveness_summary": action_effectiveness_summary,
            "recoverability_summary": recoverability_summary,
            "manual_review_backlog_summary": manual_review_backlog_summary,
            "manual_review_receipt_summary": manual_review_receipt_summary,
            "manual_review_reentry_application_summary": default_manual_review_reentry_application_summary,
            "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
            "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
            **control_plane_runtime,
            "scheduler_feedback_summary": scheduler_feedback_summary,
            "operator_action_summary": default_operator_action_summary,
            "operator_overview": default_operator_overview,
            **hybrid_summaries,
            "search_tasks": {},
        }
    try:
        stage_counts = (
            repository.stage_status_counts()
            if hasattr(repository, "stage_status_counts")
            else {}
        )
        search_counts = (
            repository.search_task_counts()
            if hasattr(repository, "search_task_counts")
            else {}
        )
        readiness_snapshot = (
            repository.analysis_readiness_snapshot()
            if hasattr(repository, "analysis_readiness_snapshot")
            else {}
        )
    except Exception:
        stage_counts = {}
        search_counts = {}
        readiness_snapshot = {}
    recommended_actions = recommend_analysis_stage_actions(
        {"analysis_blockers": readiness_snapshot.get("blockers", {})},
        gap_report=recent_gap_report,
        action_effectiveness=action_effectiveness,
        manual_review_receipt_summary=manual_review_receipt_summary,
    )
    manual_review_reentry_application_summary = (
        summarize_manual_review_reentry_application_summary(
            manual_review_receipt_summary,
            {},
            recent_gap_report,
            recent_gap_report,
            {"analysis_blockers": readiness_snapshot.get("blockers", {})},
            {"analysis_blockers": readiness_snapshot.get("blockers", {})},
        )
    )
    operator_action_summary = summarize_operator_action_surface(
        recommended_actions,
        action_effectiveness_summary,
        recoverability_summary,
    )
    operator_action_summary["manual_review_backlog_summary"] = (
        manual_review_backlog_summary
    )
    operator_action_summary["manual_review_receipt_summary"] = (
        manual_review_receipt_summary
    )
    operator_action_summary["manual_review_reentry_application_summary"] = (
        manual_review_reentry_application_summary
    )
    operator_overview = summarize_operator_overview(
        operator_action_summary,
        scheduler_feedback_summary,
    )
    operator_overview.update(hybrid_overview)
    return {
        "seed_stage": {"stored": stage_counts.get("seed_stored", 0)},
        "detail_stage": {
            "pending": stage_counts.get("detail_pending", 0),
            "archived": stage_counts.get("detail_archived", 0),
            "enriched": stage_counts.get("detail_enriched", 0),
            "blocked": stage_counts.get("detail_blocked", 0),
            "failed": stage_counts.get("detail_failed", 0),
            "replay_requested": stage_counts.get("detail_replay_requested", 0),
        },
        "analysis_stage": {
            "ready": stage_counts.get("analysis_ready", 0),
            "not_ready": stage_counts.get("analysis_not_ready", 0),
            "invalid": stage_counts.get("analysis_invalid", 0),
        },
        "analysis_blockers": readiness_snapshot.get("blockers", {}),
        "recommended_actions": recommended_actions,
        "action_effectiveness_summary": action_effectiveness_summary,
        "recoverability_summary": recoverability_summary,
        "manual_review_backlog_summary": manual_review_backlog_summary,
        "manual_review_receipt_summary": manual_review_receipt_summary,
        "manual_review_reentry_application_summary": manual_review_reentry_application_summary,
        "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
        "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
        **control_plane_runtime,
        "scheduler_feedback_summary": scheduler_feedback_summary,
        "operator_action_summary": operator_action_summary,
        "operator_overview": operator_overview,
        **hybrid_summaries,
        "search_tasks": search_counts,
    }
