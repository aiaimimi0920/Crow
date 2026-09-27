"""Assemble lightweight collection status without importing the server runtime."""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from .collection_control_state import CollectionPauseSnapshot


class StatisticsSnapshot(TypedDict):
    counts: Mapping[str, int]
    metadata: dict[str, object]


def build_runtime_snapshot(
    *,
    load_solver_status: Callable[[], Mapping[str, object]],
    load_auth_recovery: Callable[[], object],
) -> dict[str, object]:
    """Read each live status once, preserving solver-before-recovery ordering."""
    solver_status = load_solver_status()
    scopes = solver_status.get("collection_scopes", {})
    if not isinstance(scopes, dict):
        scopes = {}
    return {
        "paused": bool(solver_status.get("paused")),
        "captcha_solver": solver_status,
        "auth_recovery": load_auth_recovery(),
        "collection_scopes": scopes,
    }


def build_lightweight_status(
    snapshot: StatisticsSnapshot,
    *,
    load_api_metrics: Callable[[], Mapping[str, object]],
    empty_counts: Callable[[], Mapping[str, int]],
    load_runtime_snapshot: Callable[[], Mapping[str, object]],
    load_build_info: Callable[[], Mapping[str, str]],
    database_enabled: Callable[[], bool],
    runtime_state_label: Callable[[dict[str, object]], str],
) -> dict[str, object]:
    seed_queue_counts = snapshot["counts"]

    pending_detail = int(seed_queue_counts.get("seed_item_pending_detail", 0) or 0)
    in_progress = int(seed_queue_counts.get("seed_item_in_progress", 0) or 0)
    raw_detail_captured = int(
        seed_queue_counts.get("seed_item_raw_detail_captured", 0) or 0
    )
    analysis_in_progress = int(
        seed_queue_counts.get("seed_item_analysis_in_progress", 0) or 0
    )
    analysis_failed = int(seed_queue_counts.get("seed_item_analysis_failed", 0) or 0)
    analysis_blocked = int(seed_queue_counts.get("seed_item_analysis_blocked", 0) or 0)
    detail_completed = int(seed_queue_counts.get("seed_item_detail_completed", 0) or 0)
    detail_failed = int(seed_queue_counts.get("seed_item_detail_failed", 0) or 0)
    detail_blocked = int(seed_queue_counts.get("seed_item_detail_blocked", 0) or 0)
    raw_capture_pending = pending_detail + in_progress
    analysis_ready = raw_detail_captured + analysis_failed
    analysis_pending = raw_detail_captured + analysis_in_progress + analysis_failed
    analysis_terminal = analysis_blocked
    captured_items = analysis_pending + analysis_terminal + detail_completed
    total_items = (
        pending_detail + in_progress + captured_items + detail_failed + detail_blocked
    )
    api_metrics = load_api_metrics()
    top_level_seed_queue_counts = {
        key: int(seed_queue_counts.get(key, 0) or 0) for key in empty_counts()
    }
    runtime_snapshot = load_runtime_snapshot()
    solver_status_snapshot = runtime_snapshot["captcha_solver"]

    payload: dict[str, object] = {
        "collection_api_lightweight": True,
        "statistics": snapshot["metadata"],
        "build_info": load_build_info(),
        "capabilities": {
            "manual_captcha_report_v1": True,
            "nas_auth_recovery_v1": True,
            "stage_auth_recovery_v2": True,
        },
        "paused": runtime_snapshot["paused"],
        "total_ids": total_items,
        "captured_count": captured_items,
        "ai_finalized_count": detail_completed,
        "db_mode": database_enabled(),
        "db_total_ids": total_items,
        "db_processed_ids": detail_completed,
        "db_pending_ids": pending_detail + in_progress,
        "db_detail_captured_ids": captured_items,
        "db_analysis_pending_ids": analysis_pending,
        "raw_capture_pending_count": raw_capture_pending,
        "raw_captured_count": raw_detail_captured,
        "analysis_ready_count": analysis_ready,
        "analysis_in_progress_count": analysis_in_progress,
        "analysis_failed_count": analysis_failed,
        "analysis_pending_count": analysis_pending,
        "analysis_backlog_count": analysis_pending,
        "analysis_blocked_count": analysis_blocked,
        "analysis_finalized_count": detail_completed,
        "detail_failed_count": detail_failed,
        "detail_blocked_count": detail_blocked,
        "sniff_queue_count": int(
            seed_queue_counts.get("seed_scan_job_pending", 0) or 0
        ),
        "sniff_done_count": int(
            seed_queue_counts.get("seed_scan_job_completed", 0) or 0
        ),
        "next_batch_preview": [],
        "api_success_rate": api_metrics.get("success_rate", 0.0),
        "api_avg_response_time_ms": api_metrics.get("avg_response_time_ms", 0.0),
        "api_total_calls": api_metrics.get("total_calls", 0),
        "api_success_calls": api_metrics.get("success_calls", 0),
        **top_level_seed_queue_counts,
        "captcha_solver": solver_status_snapshot,
        "auth_recovery": runtime_snapshot["auth_recovery"],
        "collection_scopes": runtime_snapshot["collection_scopes"],
        "data_supply_recent_24h": {},
        "avm": {"lightweight_skipped": True},
        "collection_stage": {
            "lightweight": True,
            "seed_queue": seed_queue_counts,
            "seed_stage": {
                "stored": int(seed_queue_counts.get("seed_occurrence_total", 0) or 0)
            },
            "detail_stage": {
                "pending": pending_detail,
                "in_progress": in_progress,
                "raw_pending": pending_detail,
                "raw_in_progress": in_progress,
                "raw_archived": raw_detail_captured,
                "raw_captured": raw_detail_captured,
                "raw_failed": detail_failed,
                "raw_blocked": detail_blocked,
                "analysis_ready": analysis_ready,
                "analysis_in_progress": analysis_in_progress,
                "analysis_failed": analysis_failed,
                "analysis_blocked": analysis_blocked,
                "analysis_pending": analysis_pending,
                "analysis_backlog": analysis_pending,
                "archived": captured_items,
                "ai_finalized": detail_completed,
                "analysis_finalized": detail_completed,
                "failed": detail_failed,
                "blocked": detail_blocked,
            },
            "search_tasks": {
                "search_pending": int(
                    seed_queue_counts.get("seed_scan_job_pending", 0) or 0
                ),
                "search_in_progress": int(
                    seed_queue_counts.get("seed_scan_job_in_progress", 0) or 0
                ),
                "search_done": int(
                    seed_queue_counts.get("seed_scan_job_completed", 0) or 0
                ),
                "search_pruned": int(
                    seed_queue_counts.get("seed_scan_job_blocked", 0) or 0
                ),
            },
        },
    }
    payload["runtime_state"] = (
        runtime_state_label(payload) if snapshot["metadata"]["valid"] else "统计不可用"
    )
    return payload


def build_overview_payload(
    *,
    load_status: Callable[[], dict[str, object]],
    load_control: Callable[[], "CollectionPauseSnapshot"],
    load_data_root: Callable[[], Path],
    load_restart: Callable[[], object],
    load_challenge_metrics: Callable[[Path], object],
    load_auth_watcher: Callable[[Path], object],
) -> dict[str, object]:
    """Assemble observer diagnostics in their established failure order."""
    status = load_status()
    stage = cast(Mapping[str, object], status.get("collection_stage") or {})
    seed_queue = dict(cast(Mapping[str, object], stage.get("seed_queue") or {}))
    control = load_control()
    status["operator_paused"] = bool(
        control.paused and control.reason in (None, "operator")
    )
    active_data_root = load_data_root()
    return {
        "ok": True,
        "status": status,
        "runtime_state": status.get("runtime_state"),
        "engine_restart": load_restart(),
        "challenge_metrics": load_challenge_metrics(active_data_root),
        "auth_watcher": load_auth_watcher(active_data_root),
        "modules": build_overview_modules(status, seed_queue),
    }


def build_overview_modules(
    status: Mapping[str, object], seed_queue: Mapping[str, object]
) -> dict[str, object]:
    """Project collection status into the observer's three stage summaries."""
    return {
        "links": {
            "label": "商品链接采集",
            "total": _overview_count(seed_queue.get("seed_occurrence_total", 0) or 0),
            "unique_items": _overview_count(status.get("total_ids", 0) or 0),
        },
        "details": {
            "label": "商品详情页采集",
            "pending": _overview_count(status.get("raw_capture_pending_count", 0) or 0),
            "raw_captured": _overview_count(status.get("raw_captured_count", 0) or 0),
            "captured": _overview_count(status.get("captured_count", 0) or 0),
            "failed": _overview_count(status.get("detail_failed_count", 0) or 0),
            "blocked": _overview_count(status.get("detail_blocked_count", 0) or 0),
        },
        "analysis": {
            "label": "商品详情页 AI 分析",
            "ready": _overview_count(status.get("analysis_ready_count", 0) or 0),
            "pending": _overview_count(status.get("analysis_pending_count", 0) or 0),
            "failed": _overview_count(status.get("analysis_failed_count", 0) or 0),
            "blocked": _overview_count(status.get("analysis_blocked_count", 0) or 0),
            "finalized": _overview_count(
                status.get(
                    "analysis_finalized_count", status.get("ai_finalized_count", 0)
                )
                or 0
            ),
        },
    }


def _overview_count(value: object) -> int:
    return int(cast("str | int | float", value))
