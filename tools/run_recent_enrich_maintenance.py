#!/usr/bin/env python3
"""串行执行 recent enrich 维护流程。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.collection.detail_archive_fetch import fetch_missing_detail_archives
from src.collection_job_control import job_checkpoint
from src.storage.repository import create_repository_from_env
from tools.analysis_stage_planner import (
    load_manual_review_receipt_snapshot,
    recommend_analysis_stage_actions,
    summarize_action_effectiveness_snapshot,
    summarize_action_feedback,
    summarize_manual_review_backlog,
    summarize_manual_review_receipt_snapshot,
    summarize_manual_review_reentry_application_summary,
    summarize_operator_action_surface,
    summarize_operator_overview,
    summarize_recoverability_snapshot,
)
from tools.audit_recent_avm_gaps import build_recent_gap_audit
from tools.backfill_archived_details import backfill_archived_details
from tools.backfill_recent_coordinates import backfill_recent_coordinates
from tools.prepare_recent_detail_replay import prepare_recent_detail_replay
from tools.run_analysis_stage_reconcile import run_analysis_stage_reconcile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行 recent enrich maintenance workflow")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--archive-limit", type=int, default=200)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--replay-limit", type=int, default=100)
    parser.add_argument("--fetch-limit", type=int, default=20)
    parser.add_argument("--fetch-timeout", type=int, default=15)
    parser.add_argument("--reconcile-limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--extract-risk", action="store_true")
    parser.add_argument("--prepare-replay", action="store_true")
    parser.add_argument("--fetch-archives", action="store_true")
    parser.add_argument("--output-path", type=Path, default=Path("datas/avm/recent_enrich_maintenance.json"))
    return parser.parse_args()


def _collection_stage_snapshot() -> dict:
    repo = create_repository_from_env()
    if not repo.enabled or not hasattr(repo, "stage_status_counts"):
        return {
            "seed_stage": {},
            "detail_stage": {},
            "analysis_stage": {},
            "analysis_blockers": {},
            "search_tasks": {},
        }
    try:
        snapshot = repo.stage_status_counts()
        if hasattr(repo, "analysis_readiness_snapshot"):
            snapshot["analysis_blockers"] = repo.analysis_readiness_snapshot().get("blockers", {})
        else:
            snapshot["analysis_blockers"] = {}
        return snapshot
    except Exception:
        return {
            "seed_stage": {},
            "detail_stage": {},
            "analysis_stage": {},
            "analysis_blockers": {},
            "search_tasks": {},
        }


def get_collection_stage_snapshot() -> dict:
    return _collection_stage_snapshot()


def _load_manual_review_receipt_snapshot_for_maintenance(data_root: Path, repository: Any | None) -> dict[str, Any]:
    receipt_path = data_root / "avm" / "manual_review_receipts.json"
    try:
        return load_manual_review_receipt_snapshot(receipt_path, repository=repository)
    except TypeError:
        return load_manual_review_receipt_snapshot(receipt_path)


def run_recent_enrich_maintenance(
    data_root: Path,
    window_days: int,
    archive_limit: int,
    sample_limit: int,
    replay_limit: int = 100,
    fetch_limit: int = 20,
    fetch_timeout: int = 15,
    reconcile_limit: int = 200,
    dry_run: bool = False,
    extract_risk: bool = False,
    prepare_replay: bool = False,
    fetch_archives: bool = False,
    action_effectiveness: dict[str, Any] | None = None,
    repository: Any | None = None,
) -> dict:
    job_checkpoint()
    before_stage = get_collection_stage_snapshot()
    before = build_recent_gap_audit(data_root, window_days, sample_limit)
    recoverability_summary = summarize_recoverability_snapshot(before)
    manual_review_backlog_summary = summarize_manual_review_backlog(before)
    manual_review_receipt_summary = summarize_manual_review_receipt_snapshot(
        _load_manual_review_receipt_snapshot_for_maintenance(data_root, repository),
        manual_review_backlog_summary,
    )
    recommended_actions = recommend_analysis_stage_actions(
        before_stage,
        gap_report=before,
        action_effectiveness=action_effectiveness,
        manual_review_receipt_summary=manual_review_receipt_summary,
        fetch_archives=fetch_archives,
        prepare_replay=prepare_replay,
    )
    job_checkpoint()
    fetched = fetch_missing_detail_archives(
        data_root=data_root,
        limit=fetch_limit,
        timeout=fetch_timeout,
        extract_risk=extract_risk,
        dry_run=dry_run or not recommended_actions["fetch_archives"],
    ) if recommended_actions["fetch_archives"] or dry_run else {
        "limit": fetch_limit,
        "timeout": fetch_timeout,
        "extract_risk": extract_risk,
        "dry_run": dry_run,
        "candidate_count": 0,
        "fetched_count": 0,
        "failed_count": 0,
        "touched_files": 0,
        "samples": [],
        "skipped": True,
    }
    job_checkpoint()
    archived = backfill_archived_details(
        data_root=data_root,
        limit=archive_limit,
        dry_run=dry_run,
        extract_risk=extract_risk,
    ) if recommended_actions["run_archived_backfill"] or dry_run else {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "limit": archive_limit,
        "dry_run": dry_run,
        "extract_risk": extract_risk,
        "scanned_archives": 0,
        "updated_records": 0,
        "touched_files": 0,
        "samples": [],
        "skipped": True,
    }
    job_checkpoint()
    coordinates = backfill_recent_coordinates(
        data_root=data_root,
        window_days=window_days,
        dry_run=dry_run,
    ) if recommended_actions["run_coordinate_backfill"] or dry_run else {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": window_days,
        "dry_run": dry_run,
        "candidate_count": 0,
        "updated_count": 0,
        "touched_files": 0,
        "samples": [],
        "skipped": True,
    }
    job_checkpoint()
    replay = prepare_recent_detail_replay(
        data_root=data_root,
        window_days=window_days,
        limit=replay_limit,
        dry_run=dry_run or not recommended_actions["prepare_replay"],
    ) if recommended_actions["prepare_replay"] or dry_run else {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": window_days,
        "limit": replay_limit,
        "dry_run": dry_run,
        "candidate_count": 0,
        "prepared_count": 0,
        "touched_files": 0,
        "samples": [],
        "skipped": True,
    }
    job_checkpoint()
    analysis_ready_recheck = run_analysis_stage_reconcile(
        data_root=data_root,
        window_days=window_days,
        mode="analysis_ready_recheck",
        dry_run=dry_run,
        limit=reconcile_limit,
    ) if recommended_actions["suggest_analysis_ready_recheck"] or dry_run else {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "analysis_ready_recheck",
        "window_days": window_days,
        "dry_run": dry_run,
        "candidate_count": 0,
        "scanned_count": 0,
        "updated_count": 0,
        "analysis_stage_transition_count": 0,
        "analysis_ready_transition_count": 0,
        "detail_stage_transition_count": 0,
        "samples": [],
        "skipped": True,
        "skip_reason": "not_recommended",
    }
    job_checkpoint()
    stage_state_reconcile = run_analysis_stage_reconcile(
        data_root=data_root,
        window_days=window_days,
        mode="stage_state_reconcile",
        dry_run=dry_run,
        limit=reconcile_limit,
    ) if recommended_actions["suggest_stage_state_reconcile"] or dry_run else {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "stage_state_reconcile",
        "window_days": window_days,
        "dry_run": dry_run,
        "candidate_count": 0,
        "scanned_count": 0,
        "updated_count": 0,
        "analysis_stage_transition_count": 0,
        "analysis_ready_transition_count": 0,
        "detail_stage_transition_count": 0,
        "samples": [],
        "skipped": True,
        "skip_reason": "not_recommended",
    }
    job_checkpoint()
    after = build_recent_gap_audit(data_root, window_days, sample_limit)
    next_recoverability_summary = summarize_recoverability_snapshot(after)
    after_stage = get_collection_stage_snapshot()
    next_recommended_actions = recommend_analysis_stage_actions(
        after_stage,
        gap_report=after,
        action_effectiveness=action_effectiveness,
        manual_review_receipt_summary=manual_review_receipt_summary,
    )
    action_feedback = summarize_action_feedback(
        recommended_actions,
        {
            "detail_archive_fetch": fetched,
            "archived_detail_backfill": archived,
            "recent_coordinate_backfill": coordinates,
            "detail_replay_preparation": replay,
            "analysis_ready_recheck": analysis_ready_recheck,
            "stage_state_reconcile": stage_state_reconcile,
        },
    )
    executed_actions = [name for name, info in action_feedback.items() if info.get("executed")]
    productive_actions = [name for name, info in action_feedback.items() if info.get("produced_work")]
    step_to_plan_action = {
        "detail_archive_fetch": "fetch_archives",
        "archived_detail_backfill": "archived_detail_backfill",
        "recent_coordinate_backfill": "coordinate_backfill",
        "detail_replay_preparation": "prepare_replay",
        "analysis_ready_recheck": "analysis_ready_recheck",
        "stage_state_reconcile": "stage_state_reconcile",
    }
    fallback_routes_used = {}
    for source_action, target_action in dict(recommended_actions.get("fallback_routes", {}) or {}).items():
        if source_action not in set(recommended_actions.get("deprioritized_actions", []) or []):
            continue
        if target_action == "manual_review" and recommended_actions.get("manual_review_candidate"):
            fallback_routes_used[source_action] = target_action
        elif target_action in set(recommended_actions.get("priority_actions", []) or []):
            fallback_routes_used[source_action] = target_action
        elif target_action in set(recommended_actions.get("next_best_alternative_actions", []) or []):
            fallback_routes_used[source_action] = target_action
    skip_reasons = {}
    deprioritized_action_set = set(recommended_actions.get("deprioritized_actions", []) or [])
    deprioritized_reason_map = dict(recommended_actions.get("deprioritized_reason_map", {}) or {})
    for step_name, feedback in action_feedback.items():
        if feedback.get("executed"):
            continue
        plan_action = step_to_plan_action[step_name]
        if plan_action in deprioritized_action_set:
            hint = deprioritized_reason_map.get(plan_action)
            skip_reasons[step_name] = f"deprioritized:{hint}" if hint else "deprioritized"
        elif not feedback.get("recommended"):
            skip_reasons[step_name] = "not_recommended"
        else:
            skip_reasons[step_name] = "skipped"
    action_effectiveness_summary = summarize_action_effectiveness_snapshot(action_effectiveness)
    manual_review_reentry_application_summary = summarize_manual_review_reentry_application_summary(
        manual_review_receipt_summary,
        action_feedback,
        before,
        after,
        before_stage,
        after_stage,
    )
    next_manual_review_backlog_summary = summarize_manual_review_backlog(after)
    operator_action_summary = summarize_operator_action_surface(
        recommended_actions,
        action_effectiveness_summary,
        recoverability_summary,
    )
    operator_action_summary["manual_review_backlog_summary"] = manual_review_backlog_summary
    operator_action_summary["manual_review_receipt_summary"] = manual_review_receipt_summary
    operator_action_summary["manual_review_reentry_application_summary"] = manual_review_reentry_application_summary
    operator_overview = summarize_operator_overview(operator_action_summary, {})

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": window_days,
        "dry_run": dry_run,
        "extract_risk": extract_risk,
        "before_stage": before_stage,
        "recommended_actions": recommended_actions,
        "recoverability_summary": recoverability_summary,
        "operator_action_summary": operator_action_summary,
        "operator_overview": operator_overview,
        "manual_review_backlog_summary": manual_review_backlog_summary,
        "manual_review_receipt_summary": manual_review_receipt_summary,
        "manual_review_reentry_application_summary": manual_review_reentry_application_summary,
        "executed_actions": executed_actions,
        "productive_actions": productive_actions,
        "action_feedback": action_feedback,
        "fallback_routes_used": fallback_routes_used,
        "skip_reasons": skip_reasons,
        "before": before,
        "detail_archive_fetch": fetched,
        "archived_detail_backfill": archived,
        "recent_coordinate_backfill": coordinates,
        "detail_replay_preparation": replay,
        "analysis_ready_recheck": analysis_ready_recheck,
        "stage_state_reconcile": stage_state_reconcile,
        "after": after,
        "after_stage": after_stage,
        "next_recoverability_summary": next_recoverability_summary,
        "next_manual_review_backlog_summary": next_manual_review_backlog_summary,
        "next_recommended_actions": next_recommended_actions,
    }


def main() -> None:
    args = parse_args()
    report = run_recent_enrich_maintenance(
        data_root=args.data_root,
        window_days=args.window_days,
        archive_limit=args.archive_limit,
        sample_limit=args.sample_limit,
        replay_limit=args.replay_limit,
        fetch_limit=args.fetch_limit,
        fetch_timeout=args.fetch_timeout,
        reconcile_limit=args.reconcile_limit,
        dry_run=args.dry_run,
        extract_risk=args.extract_risk,
        prepare_replay=args.prepare_replay,
        fetch_archives=args.fetch_archives,
    )
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
