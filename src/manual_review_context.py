from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

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


def _manual_review_receipt_context(
    data_root: Path,
    *,
    repository: PropertyRepository | None = None,
) -> dict[str, Any]:
    avm_dir = data_root / "avm"
    action_effectiveness = load_action_effectiveness_snapshot(
        avm_dir / "data_supply_optimization_loop.json"
    )
    scheduler_progress = load_optimization_loop_progress_snapshot(
        avm_dir / "data_supply_optimization_loop.json"
    )
    scheduler_feedback_summary = summarize_scheduler_feedback_snapshot(
        scheduler_progress
    )
    recent_gap_report = load_recent_gap_audit_snapshot(
        avm_dir / "recent_gap_audit.json"
    )
    recoverability_summary = summarize_recoverability_snapshot(recent_gap_report)
    manual_review_backlog_summary = summarize_manual_review_backlog(recent_gap_report)
    manual_review_receipt_summary = summarize_manual_review_receipt_snapshot(
        _load_manual_review_receipt_snapshot_for_runtime(
            data_root, repository=repository
        ),
        manual_review_backlog_summary,
    )
    manual_review_reentry_application_summary = (
        summarize_manual_review_reentry_application_summary(
            manual_review_receipt_summary,
            {},
            recent_gap_report,
            recent_gap_report,
            {"analysis_blockers": {}},
            {"analysis_blockers": {}},
        )
    )
    recommended_actions = recommend_analysis_stage_actions(
        {"analysis_blockers": {}},
        gap_report=recent_gap_report,
        action_effectiveness=action_effectiveness,
        manual_review_receipt_summary=manual_review_receipt_summary,
    )
    action_effectiveness_summary = summarize_action_effectiveness_snapshot(
        action_effectiveness
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
        operator_action_summary, scheduler_feedback_summary
    )
    manual_review_receipt_jobs_summary = _manual_review_receipt_jobs_summary(
        data_root, repository=repository
    )
    manual_review_receipt_operations_summary = (
        _manual_review_receipt_operations_summary(data_root, repository=repository)
    )
    control_plane_runtime = _manual_review_control_plane_runtime_summary(
        data_root, repository=repository
    )
    return {
        "recommended_actions": recommended_actions,
        "manual_review_backlog_summary": manual_review_backlog_summary,
        "manual_review_receipt_summary": manual_review_receipt_summary,
        "manual_review_reentry_application_summary": manual_review_reentry_application_summary,
        "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
        "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
        **control_plane_runtime,
        "operator_action_summary": operator_action_summary,
        "operator_overview": operator_overview,
        "scheduler_feedback_summary": scheduler_feedback_summary,
    }
