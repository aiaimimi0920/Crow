"""Read-only collection runtime and PC1 authentication snapshot summaries."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, cast

from src.server_hybrid_history import _hybrid_collection_runtime_history_summary
from src.status_snapshot_values import (
    _coerce_optional_bool,
    _coerce_optional_int,
    _coerce_optional_iso_datetime,
    _coerce_optional_mapping,
    _coerce_optional_text,
    _load_json_snapshot,
)


def _collection_shared_data_root(data_root: Path) -> Path:
    expanded = Path(data_root).expanduser()
    try:
        resolved = expanded.resolve()
    except OSError:
        resolved = expanded
    if resolved.name.lower() == "datas":
        return resolved.parent
    return resolved


def _hybrid_collection_challenge_metrics_summary(data_root: Path) -> dict[str, Any]:
    runtime_summary = _hybrid_collection_runtime_summary(data_root)
    history_summary = _hybrid_collection_runtime_history_summary(data_root)
    current_reason_counts = cast(
        dict[str, int], _coerce_optional_mapping(runtime_summary.get("reason_counts"))
    )
    recent_reason_counts = cast(
        dict[str, int],
        _coerce_optional_mapping(history_summary.get("recent_reason_counts")),
    )
    current_challenge_detected_count = int(
        current_reason_counts.get("challenge_detected", 0) or 0
    )
    recent_challenge_detected_count = int(
        recent_reason_counts.get("challenge_detected", 0) or 0
    )
    current_browserless_attempt_count = max(
        int(runtime_summary.get("browserless_success_count", 0) or 0)
        + int(runtime_summary.get("browser_fallback_required_count", 0) or 0),
        0,
    )
    recent_browserless_attempt_count = max(
        int(history_summary.get("recent_browserless_success_count", 0) or 0)
        + int(history_summary.get("recent_browser_fallback_required_count", 0) or 0),
        0,
    )
    current_challenge_hit_rate = (
        current_challenge_detected_count / current_browserless_attempt_count
        if current_browserless_attempt_count > 0
        else None
    )
    recent_challenge_hit_rate = (
        recent_challenge_detected_count / recent_browserless_attempt_count
        if recent_browserless_attempt_count > 0
        else None
    )
    return {
        "available": bool(
            runtime_summary.get("available") or history_summary.get("available")
        ),
        "current_challenge_detected_count": current_challenge_detected_count,
        "current_browserless_attempt_count": current_browserless_attempt_count,
        "current_challenge_hit_rate": current_challenge_hit_rate,
        "recent_challenge_detected_count": recent_challenge_detected_count,
        "recent_browserless_attempt_count": recent_browserless_attempt_count,
        "recent_challenge_hit_rate": recent_challenge_hit_rate,
        "recent_runs": int(history_summary.get("recent_runs", 0) or 0),
        "last_reason": _coerce_optional_text(runtime_summary.get("last_reason")),
        "last_decision": _coerce_optional_text(runtime_summary.get("last_decision")),
        "last_probe_body_has_challenge": _coerce_optional_bool(
            runtime_summary.get("last_probe_body_has_challenge")
        )
        is True,
        "top_fallback_reason": _coerce_optional_text(
            runtime_summary.get("top_fallback_reason")
        ),
        "recent_top_fallback_reason": _coerce_optional_text(
            history_summary.get("recent_top_fallback_reason")
        ),
    }


def _pc1_auth_auto_resume_state_summary(data_root: Path) -> dict[str, Any]:
    shared_root = _collection_shared_data_root(data_root)
    raw = _load_json_snapshot(
        shared_root / "secrets" / "pc1-auth-auto-resume-state.json"
    )
    if not raw:
        return {
            "available": False,
            "mode": None,
            "status": None,
            "started_at": None,
            "completed_at": None,
            "wait_elapsed_seconds": None,
            "poll_seconds": 0,
            "max_wait_seconds": 0,
            "api_base": None,
            "cdp_endpoint": None,
            "last_error": None,
        }

    started_at = _coerce_optional_iso_datetime(raw.get("started_at"))
    completed_at = _coerce_optional_iso_datetime(raw.get("completed_at"))
    wait_elapsed_seconds = None
    if started_at is not None:
        ended_at = completed_at or datetime.datetime.now(datetime.timezone.utc)
        wait_elapsed_seconds = max(int((ended_at - started_at).total_seconds()), 0)

    poll_seconds = _coerce_optional_int(raw.get("poll_seconds"))
    if poll_seconds is None or poll_seconds < 0:
        poll_seconds = 0
    max_wait_seconds = _coerce_optional_int(raw.get("max_wait_seconds"))
    if max_wait_seconds is None or max_wait_seconds < 0:
        max_wait_seconds = 0

    return {
        "available": True,
        "mode": _coerce_optional_text(raw.get("mode")),
        "status": _coerce_optional_text(raw.get("status")),
        "started_at": _coerce_optional_text(raw.get("started_at")),
        "completed_at": _coerce_optional_text(raw.get("completed_at")),
        "wait_elapsed_seconds": wait_elapsed_seconds,
        "poll_seconds": poll_seconds,
        "max_wait_seconds": max_wait_seconds,
        "api_base": _coerce_optional_text(raw.get("api_base")),
        "cdp_endpoint": _coerce_optional_text(raw.get("cdp_endpoint")),
        "last_error": _coerce_optional_text(raw.get("last_error")),
    }


def _hybrid_collection_runtime_summary(data_root: Path) -> dict[str, Any]:
    raw = _load_json_snapshot(data_root / "avm" / "hybrid_seed_collection_runtime.json")
    if not raw:
        return {
            "available": False,
            "decision_counts": {},
            "reason_counts": {},
            "top_fallback_reason": None,
            "requested_mode": None,
            "effective_mode_source": None,
            "operator_action_hint": None,
            "effective_mode_counts": {},
            "guidance_applied_count": 0,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_mode_pin_active": False,
            "browserless_success_count": 0,
            "browser_fallback_required_count": 0,
            "browser_worker_dispatched_count": 0,
            "last_decision": None,
            "last_reason": None,
            "last_effective_mode": None,
            "last_task_url": None,
            "last_task_page": None,
            "last_task_location_code": None,
            "last_task_category": None,
            "last_probe_item_count": 0,
            "last_probe_has_script": False,
            "last_probe_body_has_login": False,
            "last_probe_body_has_captcha": False,
            "last_probe_body_has_punish": False,
            "last_probe_body_has_challenge": False,
            "last_submit_batch_status": None,
            "last_submit_batch_new": 0,
            "last_submit_progress_status": None,
            "last_browser_fallback_opened": False,
        }

    decision_counts = {
        normalized_key: parsed_value
        for key, value in _coerce_optional_mapping(raw.get("decision_counts")).items()
        if (normalized_key := _coerce_optional_text(key)) is not None
        and (parsed_value := _coerce_optional_int(value)) is not None
        and parsed_value >= 0
    }
    reason_counts = {
        normalized_key: parsed_value
        for key, value in _coerce_optional_mapping(raw.get("reason_counts")).items()
        if (normalized_key := _coerce_optional_text(key)) is not None
        and (parsed_value := _coerce_optional_int(value)) is not None
        and parsed_value > 0
    }
    top_fallback_reason = _coerce_optional_text(raw.get("top_fallback_reason"))
    if top_fallback_reason is None and reason_counts:
        top_fallback_reason = sorted(
            reason_counts.items(), key=lambda item: (-item[1], item[0])
        )[0][0]
    last_task = _coerce_optional_mapping(raw.get("last_task"))
    last_probe_summary = _coerce_optional_mapping(raw.get("last_probe_summary"))
    last_submit_result = _coerce_optional_mapping(raw.get("last_submit_result"))
    last_batch_result = _coerce_optional_mapping(last_submit_result.get("batch"))
    last_progress_result = _coerce_optional_mapping(last_submit_result.get("progress"))
    effective_mode_counts = {
        normalized_key: parsed_value
        for key, value in _coerce_optional_mapping(
            raw.get("effective_mode_counts")
        ).items()
        if (normalized_key := _coerce_optional_text(key)) is not None
        and (parsed_value := _coerce_optional_int(value)) is not None
        and parsed_value >= 0
    }
    iterations = _coerce_optional_int(raw.get("iterations"))
    if iterations is None or iterations < 0:
        iterations = 0
    guidance_applied_count = _coerce_optional_int(raw.get("guidance_applied_count"))
    if guidance_applied_count is None or guidance_applied_count < 0:
        guidance_applied_count = 0
    last_probe_item_count = _coerce_optional_int(last_probe_summary.get("item_count"))
    if last_probe_item_count is None or last_probe_item_count < 0:
        last_probe_item_count = 0
    last_submit_batch_new = _coerce_optional_int(last_batch_result.get("new"))
    if last_submit_batch_new is None or last_submit_batch_new < 0:
        last_submit_batch_new = 0
    last_task_page = _coerce_optional_int(last_task.get("page"))
    if last_task_page is not None and last_task_page < 0:
        last_task_page = None
    return {
        "available": True,
        "generated_at": _coerce_optional_text(raw.get("generated_at")),
        "runner_mode": _coerce_optional_text(raw.get("runner_mode")),
        "requested_mode": _coerce_optional_text(raw.get("requested_mode")),
        "effective_mode_source": _coerce_optional_text(
            raw.get("effective_mode_source")
        ),
        "operator_action_hint": _coerce_optional_text(raw.get("operator_action_hint")),
        "loop_mode": _coerce_optional_bool(raw.get("loop_mode")) is True,
        "submit_enabled": _coerce_optional_bool(raw.get("submit_enabled")) is True,
        "session_id": _coerce_optional_text(raw.get("session_id")),
        "iterations": iterations,
        "decision_counts": decision_counts,
        "reason_counts": reason_counts,
        "top_fallback_reason": top_fallback_reason,
        "termination_reason": _coerce_optional_text(raw.get("termination_reason")),
        "effective_mode_counts": effective_mode_counts,
        "guidance_applied_count": guidance_applied_count,
        "guidance_status": _coerce_optional_text(raw.get("guidance_status")),
        "recovery_policy_status": _coerce_optional_text(
            raw.get("recovery_policy_status")
        ),
        "recovery_policy_mode_pin_active": _coerce_optional_bool(
            raw.get("recovery_policy_mode_pin_active")
        )
        is True,
        "browserless_success_count": int(
            decision_counts.get("browserless_success", 0) or 0
        ),
        "browser_fallback_required_count": int(
            decision_counts.get("browser_fallback_required", 0) or 0
        ),
        "browser_worker_dispatched_count": int(
            decision_counts.get("browser_worker_dispatched", 0) or 0
        ),
        "last_decision": _coerce_optional_text(raw.get("last_decision")),
        "last_reason": _coerce_optional_text(raw.get("last_reason")),
        "last_effective_mode": _coerce_optional_text(raw.get("last_effective_mode"))
        or _coerce_optional_text(raw.get("effective_mode")),
        "last_task_url": _coerce_optional_text(last_task.get("url")),
        "last_task_page": last_task_page,
        "last_task_location_code": _coerce_optional_text(
            last_task.get("location_code")
        ),
        "last_task_category": _coerce_optional_text(last_task.get("category")),
        "last_probe_item_count": last_probe_item_count,
        "last_probe_has_script": _coerce_optional_bool(
            last_probe_summary.get("has_script")
        )
        is True,
        "last_probe_body_has_login": _coerce_optional_bool(
            last_probe_summary.get("body_has_login")
        )
        is True,
        "last_probe_body_has_captcha": _coerce_optional_bool(
            last_probe_summary.get("body_has_captcha")
        )
        is True,
        "last_probe_body_has_punish": _coerce_optional_bool(
            last_probe_summary.get("body_has_punish")
        )
        is True,
        "last_probe_body_has_challenge": _coerce_optional_bool(
            last_probe_summary.get("body_has_challenge")
        )
        is True,
        "last_submit_batch_status": _coerce_optional_text(
            last_batch_result.get("status")
        ),
        "last_submit_batch_new": last_submit_batch_new,
        "last_submit_progress_status": _coerce_optional_text(
            last_progress_result.get("status")
        ),
        "last_browser_fallback_opened": _coerce_optional_bool(
            raw.get("last_browser_fallback_opened")
        )
        is True,
    }


__all__ = [
    "_collection_shared_data_root",
    "_hybrid_collection_challenge_metrics_summary",
    "_pc1_auth_auto_resume_state_summary",
    "_hybrid_collection_runtime_summary",
]
