from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from src.server_hybrid_overview import (
    _hybrid_collection_operator_digest_overview_fields,
    _hybrid_collection_operator_escalation_event_overview_fields,
    _hybrid_collection_operator_final_guidance_overview_fields,
    _hybrid_collection_operator_guidance_overview_fields,
    _hybrid_collection_operator_intervention_policy_overview_fields,
    _hybrid_collection_operator_mode_switch_overview_fields,
    _hybrid_collection_operator_recovery_policy_event_overview_fields,
    _hybrid_collection_operator_recovery_policy_overview_fields,
)
from src.status_snapshot_values import (
    _coerce_optional_bool,
    _coerce_optional_float,
    _coerce_optional_int,
    _coerce_optional_mapping,
    _coerce_optional_text,
    _load_jsonl_snapshots,
)
from src.utc_timestamps import _utc_timestamp_leq


def _hybrid_collection_strategy_guidance(
    latest_summary: dict[str, Any],
    history_summary: dict[str, Any],
) -> dict[str, Any]:
    history_available = _coerce_optional_bool(history_summary.get("available")) is True
    if not history_available:
        return {
            "guidance_status": "no_history_available",
            "priority": "info",
            "recommended_mode": "hybrid",
            "recommended_actions": ["collect_more_hybrid_runtime_history"],
            "top_guidance_reason": "history_unavailable",
        }

    recent_runs = _coerce_optional_int(history_summary.get("recent_runs")) or 0
    success_rate = (
        _coerce_optional_float(history_summary.get("recent_browserless_success_rate"))
        or 0.0
    )
    if success_rate < 0:
        success_rate = 0.0
    elif success_rate > 1:
        success_rate = 1.0
    fallback_count = (
        _coerce_optional_int(
            history_summary.get("recent_browser_fallback_required_count")
        )
        or 0
    )
    top_fallback_reason = _coerce_optional_text(
        history_summary.get("recent_top_fallback_reason")
    )
    top_termination_reason = _coerce_optional_text(
        history_summary.get("recent_top_termination_reason")
    )
    last_decision = _coerce_optional_text(latest_summary.get("last_decision"))

    if (
        top_fallback_reason == "challenge_detected"
        and fallback_count >= 2
        and top_termination_reason == "fallback_escalation_threshold_reached"
    ):
        return {
            "guidance_status": "investigate_challenge_spike",
            "priority": "high",
            "recommended_mode": "browser",
            "recommended_actions": [
                "review_challenge_recovery_path",
                "switch_operator_mode_to_browser",
                "inspect_cookie_or_session_stability",
            ],
            "top_guidance_reason": "challenge_detected",
        }

    if recent_runs >= 3 and fallback_count > 0 and success_rate < 0.5:
        return {
            "guidance_status": "prefer_browser_fallback",
            "priority": "warning",
            "recommended_mode": "browser",
            "recommended_actions": [
                "prefer_browser_fallback_for_next_runs",
                "review_browserless_failure_reasons",
            ],
            "top_guidance_reason": str(
                top_fallback_reason or "browserless_low_success_rate"
            ),
        }

    if recent_runs < 3:
        return {
            "guidance_status": "insufficient_history",
            "priority": "info",
            "recommended_mode": "hybrid",
            "recommended_actions": ["collect_more_hybrid_runtime_history"],
            "top_guidance_reason": "insufficient_history",
        }

    if last_decision == "browserless_success" and success_rate >= 0.8:
        return {
            "guidance_status": "keep_hybrid",
            "priority": "info",
            "recommended_mode": "hybrid",
            "recommended_actions": ["keep_browserless_fast_path_enabled"],
            "top_guidance_reason": "browserless_success_stable",
        }

    return {
        "guidance_status": "monitor_hybrid_runtime",
        "priority": "info",
        "recommended_mode": "hybrid",
        "recommended_actions": ["monitor_recent_fallback_reasons"],
        "top_guidance_reason": str(top_fallback_reason or "mixed_runtime_signals"),
    }


def _hybrid_collection_recovery_policy(
    data_root: Path,
    latest_summary: dict[str, Any],
    history_summary: dict[str, Any],
    guidance: dict[str, Any],
    switch_summary: dict[str, Any],
    recovery_event_summary: dict[str, Any],
) -> dict[str, Any]:
    latest_summary = _coerce_optional_mapping(latest_summary)
    history_summary = _coerce_optional_mapping(history_summary)
    guidance = _coerce_optional_mapping(guidance)
    switch_summary = _coerce_optional_mapping(switch_summary)
    recovery_event_summary = _coerce_optional_mapping(recovery_event_summary)
    guidance_status = _coerce_optional_text(guidance.get("guidance_status"))
    guidance_recommended_mode = _coerce_optional_text(guidance.get("recommended_mode"))
    top_switch_target_mode = _coerce_optional_text(
        switch_summary.get("top_target_mode")
    )
    top_switch_guidance_reason = _coerce_optional_text(
        switch_summary.get("top_guidance_reason")
    )
    last_switch_at = _coerce_optional_text(switch_summary.get("last_switch_at"))
    recent_switch_count = (
        _coerce_optional_int(switch_summary.get("recent_switch_count")) or 0
    )
    if recent_switch_count < 0:
        recent_switch_count = 0
    recent_browserless_success_rate = (
        _coerce_optional_float(history_summary.get("recent_browserless_success_rate"))
        or 0.0
    )
    if recent_browserless_success_rate < 0:
        recent_browserless_success_rate = 0.0
    elif recent_browserless_success_rate > 1:
        recent_browserless_success_rate = 1.0
    history_available = _coerce_optional_bool(history_summary.get("available")) is True
    if not history_available:
        return {
            "policy_status": "no_history_available",
            "priority": "info",
            "effective_recommended_mode": guidance_recommended_mode or "hybrid",
            "mode_pin_active": False,
            "recommended_actions": ["collect_more_hybrid_runtime_history"],
            "top_policy_reason": "history_unavailable",
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_recommended_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": recent_browserless_success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
        }

    guidance_mode = guidance_recommended_mode or "hybrid"
    guidance_priority = _coerce_optional_text(guidance.get("priority")) or "info"
    success_rate = recent_browserless_success_rate
    top_policy_reason = (
        top_switch_guidance_reason
        or _coerce_optional_text(guidance.get("top_guidance_reason"))
        or "mixed_runtime_signals"
    )
    last_recovery_transition_kind = _coerce_optional_text(
        recovery_event_summary.get("last_transition_kind")
    )
    last_recovery_to_policy_status = _coerce_optional_text(
        recovery_event_summary.get("last_to_policy_status")
    )
    last_recovery_transition_at = _coerce_optional_text(
        recovery_event_summary.get("last_transition_at")
    )
    last_decision = _coerce_optional_text(latest_summary.get("last_decision")) or ""
    last_reason = _coerce_optional_text(latest_summary.get("last_reason")) or ""
    recovery_transition_kind_counts = _coerce_optional_mapping(
        recovery_event_summary.get("recent_transition_kind_counts")
    )
    pin_released_count = (
        _coerce_optional_int(recovery_transition_kind_counts.get("pin_released")) or 0
    )
    pin_activated_count = (
        _coerce_optional_int(recovery_transition_kind_counts.get("pin_activated")) or 0
    )

    budget_total = 1
    budget_attempts_used = 0
    if last_recovery_transition_kind == "pin_released" and last_recovery_transition_at:
        history_entries = _load_jsonl_snapshots(
            data_root / "avm" / "hybrid_seed_collection_runtime_history.jsonl"
        )
        for entry in history_entries:
            generated_at = _coerce_optional_text(entry.get("generated_at"))
            if not generated_at or _utc_timestamp_leq(
                generated_at, last_recovery_transition_at
            ):
                continue
            decision_counts = _coerce_optional_mapping(entry.get("decision_counts"))
            browserless_success_count = (
                _coerce_optional_int(decision_counts.get("browserless_success")) or 0
            )
            if browserless_success_count < 0:
                browserless_success_count = 0
            browser_fallback_required_count = (
                _coerce_optional_int(decision_counts.get("browser_fallback_required"))
                or 0
            )
            if browser_fallback_required_count < 0:
                browser_fallback_required_count = 0
            budget_attempts_used += browserless_success_count
            budget_attempts_used += browser_fallback_required_count
        latest_generated_at = _coerce_optional_text(latest_summary.get("generated_at"))
        if (
            budget_attempts_used == 0
            and latest_generated_at
            and not _utc_timestamp_leq(latest_generated_at, last_recovery_transition_at)
            and last_decision in {"browserless_success", "browser_fallback_required"}
        ):
            budget_attempts_used = 1
    budget_remaining = max(0, budget_total - budget_attempts_used)

    common_policy_fields = {
        "hybrid_retrial_budget_total": budget_total,
        "hybrid_retrial_attempts_used": budget_attempts_used,
        "hybrid_retrial_budget_remaining": budget_remaining,
        "last_recovery_transition_kind": last_recovery_transition_kind,
        "last_recovery_transition_at": last_recovery_transition_at,
    }

    if (
        pin_released_count >= 2
        and pin_activated_count >= 2
        and last_decision == "browser_fallback_required"
        and last_reason == "challenge_detected"
    ):
        return {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "recommended_actions": [
                "investigate_repeated_repin_cycle",
                "keep_browser_mode_pinned",
                "inspect_session_recovery_stability",
            ],
            "top_policy_reason": "repeated_repin_cycle_detected",
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
            **common_policy_fields,
        }

    if (
        last_recovery_transition_kind == "pin_released"
        and last_recovery_to_policy_status == "allow_hybrid_retrial"
        and last_decision == "browser_fallback_required"
        and last_reason == "challenge_detected"
    ):
        return {
            "policy_status": "re_pin_browser_mode_temporarily",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "recommended_actions": [
                "re_pin_browser_mode",
                "stop_immediate_hybrid_retrial",
                "review_challenge_recovery_path",
            ],
            "top_policy_reason": "challenge_detected_after_release",
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
            **common_policy_fields,
        }

    if (
        recent_switch_count >= 2
        and top_switch_target_mode == "browser"
        and guidance_mode == "browser"
    ):
        return {
            "policy_status": "pin_browser_mode_temporarily",
            "priority": "high" if guidance_priority == "high" else "warning",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "recommended_actions": [
                "keep_browser_mode_pinned",
                "review_browserless_recovery_before_retry",
            ],
            "top_policy_reason": top_policy_reason,
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
            **common_policy_fields,
        }

    if (
        recent_switch_count >= 1
        and top_switch_target_mode == "browser"
        and guidance_mode == "hybrid"
        and success_rate >= 0.8
    ):
        return {
            "policy_status": "allow_hybrid_retrial",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "recommended_actions": [
                "allow_hybrid_retrial",
                "continue_monitoring_mode_switch_events",
            ],
            "top_policy_reason": "browser_recovery_window_stabilized",
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
            **common_policy_fields,
        }

    if guidance_mode == "browser":
        return {
            "policy_status": "follow_browser_guidance",
            "priority": guidance_priority,
            "effective_recommended_mode": "browser",
            "mode_pin_active": False,
            "recommended_actions": list(
                cast(
                    Iterable[object],
                    guidance.get("recommended_actions") or ["follow_browser_guidance"],
                )
            ),
            "top_policy_reason": top_policy_reason,
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
            **common_policy_fields,
        }

    if guidance_mode == "hybrid" and recent_switch_count == 0:
        return {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "recommended_actions": ["keep_browserless_fast_path_enabled"],
            "top_policy_reason": _coerce_optional_text(
                guidance.get("top_guidance_reason")
            )
            or "hybrid_stable",
            "guidance_status": guidance_status,
            "guidance_recommended_mode": guidance_mode,
            "recent_mode_switch_count": recent_switch_count,
            "recent_browserless_success_rate": success_rate,
            "top_switch_target_mode": top_switch_target_mode,
            "top_switch_guidance_reason": top_switch_guidance_reason,
            "last_switch_at": last_switch_at,
            **common_policy_fields,
        }

    return {
        "policy_status": "monitor_hybrid_recovery",
        "priority": "info",
        "effective_recommended_mode": guidance_mode,
        "mode_pin_active": False,
        "recommended_actions": ["continue_monitoring_mode_switch_events"],
        "top_policy_reason": top_policy_reason,
        "guidance_status": guidance_status,
        "guidance_recommended_mode": guidance_mode,
        "recent_mode_switch_count": recent_switch_count,
        "recent_browserless_success_rate": success_rate,
        "top_switch_target_mode": top_switch_target_mode,
        "top_switch_guidance_reason": top_switch_guidance_reason,
        "last_switch_at": last_switch_at,
        **common_policy_fields,
    }


__all__ = [
    "_hybrid_collection_operator_intervention_policy_overview_fields",
    "_hybrid_collection_operator_final_guidance_overview_fields",
    "_hybrid_collection_operator_digest_overview_fields",
    "_hybrid_collection_strategy_guidance",
    "_hybrid_collection_operator_guidance_overview_fields",
    "_hybrid_collection_operator_mode_switch_overview_fields",
    "_hybrid_collection_recovery_policy",
    "_hybrid_collection_operator_recovery_policy_overview_fields",
    "_hybrid_collection_operator_recovery_policy_event_overview_fields",
    "_hybrid_collection_operator_escalation_event_overview_fields",
]
