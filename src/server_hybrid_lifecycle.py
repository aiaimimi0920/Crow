from __future__ import annotations

from typing import Any

from src.status_snapshot_values import (
    _coerce_optional_bool,
    _coerce_optional_float,
    _coerce_optional_int,
    _coerce_optional_mapping,
    _coerce_optional_text,
)


def _hybrid_collection_lifecycle_state_summary(
    runtime_summary: dict[str, Any],
    recovery_policy: dict[str, Any],
    unresolved_window_summary: dict[str, Any],
    priority_mix_summary: dict[str, Any],
) -> dict[str, Any]:
    runtime_summary = _coerce_optional_mapping(runtime_summary)
    recovery_policy = _coerce_optional_mapping(recovery_policy)
    unresolved_window_summary = _coerce_optional_mapping(unresolved_window_summary)
    priority_mix_summary = _coerce_optional_mapping(priority_mix_summary)
    active_high_priority_unresolved_count = 0
    active_unresolved_priority = None
    priority_hint = "no_active_priority_backlog"
    window_open = (
        _coerce_optional_bool(unresolved_window_summary.get("window_open")) is True
    )
    runtime_available = _coerce_optional_bool(runtime_summary.get("available")) is True
    if window_open:
        active_high_priority_unresolved_count = (
            _coerce_optional_int(
                priority_mix_summary.get("recent_high_priority_unresolved_count")
            )
            or 0
        )
        if active_high_priority_unresolved_count < 0:
            active_high_priority_unresolved_count = 0
        active_unresolved_priority = _coerce_optional_text(
            priority_mix_summary.get("top_recent_unresolved_priority")
        )
        if active_high_priority_unresolved_count > 0:
            priority_hint = "high_priority_backlog_present"
        elif active_unresolved_priority:
            priority_hint = "non_high_priority_backlog_present"
        else:
            priority_hint = "unresolved_priority_backlog_present"
    if not runtime_available and not recovery_policy:
        return {
            "available": False,
            "lifecycle_state": "unknown",
            "lifecycle_reason": "no_runtime_signals",
            "recommended_follow_up": "collect_runtime_history",
            "suggested_mode": "hybrid",
            "operator_action_hint": "collect runtime history; suggested mode=hybrid",
            "priority_hint": "no_priority_data",
            "active_unresolved_priority": active_unresolved_priority,
            "active_high_priority_unresolved_count": active_high_priority_unresolved_count,
            "policy_status": None,
            "window_open": False,
        }

    runtime_policy_status = (
        _coerce_optional_text(runtime_summary.get("recovery_policy_status")) or ""
    )
    computed_policy_status = (
        _coerce_optional_text(recovery_policy.get("policy_status")) or ""
    )
    policy_status = runtime_policy_status or computed_policy_status
    runtime_operator_action_hint = _coerce_optional_text(
        runtime_summary.get("operator_action_hint")
    )

    def _resolve_action_hint(lifecycle_state: str, suggested_mode: str) -> str:
        if runtime_operator_action_hint is not None:
            return runtime_operator_action_hint
        if lifecycle_state == "escalated":
            if priority_hint == "high_priority_backlog_present":
                return f"inspect unresolved high-priority backlog; suggested mode={suggested_mode}"
            return f"prefer browser and investigate escalation; suggested mode={suggested_mode}"
        if lifecycle_state == "retrial_window_open":
            return f"continue hybrid with budget watch; suggested mode={suggested_mode}"
        if lifecycle_state == "recovering":
            return f"monitor until stable; suggested mode={suggested_mode}"
        if lifecycle_state == "steady":
            return f"keep hybrid; suggested mode={suggested_mode}"
        return f"collect runtime history; suggested mode={suggested_mode}"

    if window_open:
        return {
            "available": True,
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "operator_action_hint": _resolve_action_hint("escalated", "browser"),
            "priority_hint": priority_hint,
            "active_unresolved_priority": active_unresolved_priority,
            "active_high_priority_unresolved_count": active_high_priority_unresolved_count,
            "policy_status": policy_status or None,
            "window_open": True,
        }
    if policy_status == "allow_hybrid_retrial":
        return {
            "available": True,
            "lifecycle_state": "retrial_window_open",
            "lifecycle_reason": "hybrid_retrial_budget_active",
            "recommended_follow_up": "continue_hybrid_with_budget_watch",
            "suggested_mode": "hybrid",
            "operator_action_hint": _resolve_action_hint(
                "retrial_window_open", "hybrid"
            ),
            "priority_hint": priority_hint,
            "active_unresolved_priority": active_unresolved_priority,
            "active_high_priority_unresolved_count": active_high_priority_unresolved_count,
            "policy_status": policy_status,
            "window_open": False,
        }
    if policy_status == "monitor_hybrid_recovery":
        return {
            "available": True,
            "lifecycle_state": "recovering",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "operator_action_hint": _resolve_action_hint("recovering", "hybrid"),
            "priority_hint": priority_hint,
            "active_unresolved_priority": active_unresolved_priority,
            "active_high_priority_unresolved_count": active_high_priority_unresolved_count,
            "policy_status": policy_status,
            "window_open": False,
        }
    return {
        "available": True,
        "lifecycle_state": "steady",
        "lifecycle_reason": "browserless_fast_path_stable",
        "recommended_follow_up": "keep_hybrid",
        "suggested_mode": "hybrid",
        "operator_action_hint": _resolve_action_hint("steady", "hybrid"),
        "priority_hint": priority_hint,
        "active_unresolved_priority": active_unresolved_priority,
        "active_high_priority_unresolved_count": active_high_priority_unresolved_count,
        "policy_status": policy_status or "steady_hybrid",
        "window_open": False,
    }


def _hybrid_collection_action_hint_consistency_summary(
    runtime_summary: dict[str, Any],
    lifecycle_summary: dict[str, Any],
) -> dict[str, Any]:
    runtime_summary = _coerce_optional_mapping(runtime_summary)
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    runtime_hint = runtime_summary.get("operator_action_hint")
    lifecycle_hint = lifecycle_summary.get("operator_action_hint")
    available = (
        _coerce_optional_bool(runtime_summary.get("available")) is True
        or _coerce_optional_bool(lifecycle_summary.get("available")) is True
    )
    if not available:
        return {
            "available": False,
            "runtime_operator_action_hint": None,
            "lifecycle_operator_action_hint": None,
            "hints_match": False,
            "consistency_status": "no_hint_available",
            "drift_reason": None,
            "consistency_severity": "info",
            "severity_reason": None,
            "hint_source_preference": None,
            "preferred_hint_source_detail": None,
            "preferred_hint_explanation": None,
            "preferred_operator_action_hint": None,
        }

    runtime_hint_str = _coerce_optional_text(runtime_hint)
    lifecycle_hint_str = _coerce_optional_text(lifecycle_hint)
    if (
        runtime_hint_str
        and lifecycle_hint_str
        and runtime_hint_str == lifecycle_hint_str
    ):
        consistency_status = "aligned"
        hints_match = True
        drift_reason = None
        consistency_severity = "info"
        severity_reason = "aligned_hints"
        hint_source_preference = "runtime_preferred"
        preferred_hint_source_detail = "runtime_aligned"
        preferred_hint_explanation = "Runtime and lifecycle action hints are aligned; using the runtime-preferred hint."
    elif runtime_hint_str and lifecycle_hint_str:
        consistency_status = "mismatch"
        hints_match = False
        drift_reason = "value_mismatch"
        consistency_severity = "high"
        severity_reason = "conflicting_runtime_and_lifecycle_hints"
        hint_source_preference = "runtime_preferred"
        preferred_hint_source_detail = "runtime_mismatch_wins"
        preferred_hint_explanation = "Runtime and lifecycle action hints conflict; using the runtime-preferred hint."
    elif runtime_hint_str:
        consistency_status = "runtime_only"
        hints_match = False
        drift_reason = "lifecycle_missing"
        consistency_severity = "warning"
        severity_reason = "lifecycle_missing_runtime_only"
        hint_source_preference = "runtime_preferred"
        preferred_hint_source_detail = "runtime_only_available"
        preferred_hint_explanation = (
            "Lifecycle action hint is missing; using the runtime-only hint."
        )
    elif lifecycle_hint_str:
        consistency_status = "lifecycle_only"
        hints_match = False
        drift_reason = "runtime_missing"
        consistency_severity = "warning"
        severity_reason = "runtime_missing_lifecycle_fallback"
        hint_source_preference = "lifecycle_preferred"
        preferred_hint_source_detail = "lifecycle_fallback_used"
        preferred_hint_explanation = (
            "Runtime action hint is missing; using the lifecycle fallback hint."
        )
    else:
        consistency_status = "no_hint_available"
        hints_match = False
        drift_reason = None
        consistency_severity = "info"
        severity_reason = None
        hint_source_preference = None
        preferred_hint_source_detail = None
        preferred_hint_explanation = None

    return {
        "available": True,
        "runtime_operator_action_hint": runtime_hint_str,
        "lifecycle_operator_action_hint": lifecycle_hint_str,
        "hints_match": hints_match,
        "consistency_status": consistency_status,
        "drift_reason": drift_reason,
        "consistency_severity": consistency_severity,
        "severity_reason": severity_reason,
        "hint_source_preference": hint_source_preference,
        "preferred_hint_source_detail": preferred_hint_source_detail,
        "preferred_hint_explanation": preferred_hint_explanation,
        "preferred_operator_action_hint": runtime_hint_str or lifecycle_hint_str,
    }


def _hybrid_collection_operator_intervention_policy_summary(
    lifecycle_summary: dict[str, Any],
    action_hint_consistency_summary: dict[str, Any],
    resolution_trend_summary: dict[str, Any],
    recovery_latency_summary: dict[str, Any],
) -> dict[str, Any]:
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    action_hint_consistency_summary = _coerce_optional_mapping(
        action_hint_consistency_summary
    )
    resolution_trend_summary = _coerce_optional_mapping(resolution_trend_summary)
    recovery_latency_summary = _coerce_optional_mapping(recovery_latency_summary)
    available = (
        _coerce_optional_bool(lifecycle_summary.get("available")) is True
        or _coerce_optional_bool(action_hint_consistency_summary.get("available"))
        is True
    )
    if not available:
        return {
            "available": False,
            "intervention_status": "unknown",
            "intervention_required": False,
            "intervention_priority": "info",
            "intervention_reason": "no_runtime_signals",
            "preferred_operator_action_hint": None,
            "suggested_mode": None,
            "lifecycle_state": None,
            "window_open": False,
            "active_high_priority_unresolved_count": 0,
            "hint_consistency_status": None,
            "hint_consistency_severity": None,
            "resolution_trend_available": False,
            "recent_unresolved_count": 0,
            "recent_resolution_rate": 0.0,
            "recovery_latency_available": False,
            "last_recovery_latency_minutes": None,
        }

    lifecycle_state = (
        _coerce_optional_text(lifecycle_summary.get("lifecycle_state")) or "unknown"
    )
    lifecycle_reason = _coerce_optional_text(lifecycle_summary.get("lifecycle_reason"))
    if lifecycle_reason is None:
        if lifecycle_state == "escalated":
            lifecycle_reason = "unresolved_escalation_window_open"
        elif lifecycle_state == "retrial_window_open":
            lifecycle_reason = "hybrid_retrial_budget_active"
        elif lifecycle_state == "recovering":
            lifecycle_reason = "recovery_policy_monitoring_active"
        elif lifecycle_state == "steady":
            lifecycle_reason = "browserless_fast_path_stable"
        else:
            lifecycle_reason = "no_runtime_signals"
    priority_hint = _coerce_optional_text(lifecycle_summary.get("priority_hint")) or ""
    active_high_priority_unresolved_count = (
        _coerce_optional_int(
            lifecycle_summary.get("active_high_priority_unresolved_count")
        )
        or 0
    )
    if active_high_priority_unresolved_count < 0:
        active_high_priority_unresolved_count = 0
    suggested_mode = _coerce_optional_text(lifecycle_summary.get("suggested_mode"))
    if suggested_mode is None:
        if lifecycle_state == "escalated":
            suggested_mode = "browser"
        elif lifecycle_state in {"retrial_window_open", "recovering", "steady"}:
            suggested_mode = "hybrid"
    preferred_operator_action_hint = _coerce_optional_text(
        action_hint_consistency_summary.get("preferred_operator_action_hint")
    )
    if preferred_operator_action_hint is None:
        preferred_operator_action_hint = _coerce_optional_text(
            lifecycle_summary.get("operator_action_hint")
        )
    hint_consistency_status = _coerce_optional_text(
        action_hint_consistency_summary.get("consistency_status")
    )
    hint_consistency_severity = _coerce_optional_text(
        action_hint_consistency_summary.get("consistency_severity")
    )
    resolution_trend_available = (
        _coerce_optional_bool(resolution_trend_summary.get("available")) is True
    )
    recovery_latency_available = (
        _coerce_optional_bool(recovery_latency_summary.get("available")) is True
    )
    recent_unresolved_count = (
        _coerce_optional_int(resolution_trend_summary.get("recent_unresolved_count"))
        or 0
    )
    if recent_unresolved_count < 0:
        recent_unresolved_count = 0
    recent_resolution_rate = (
        _coerce_optional_float(resolution_trend_summary.get("recent_resolution_rate"))
        or 0.0
    )
    if recent_resolution_rate < 0:
        recent_resolution_rate = 0.0
    elif recent_resolution_rate > 1:
        recent_resolution_rate = 1.0
    last_recovery_latency_minutes = _coerce_optional_float(
        recovery_latency_summary.get("last_recovery_latency_minutes")
    )
    if last_recovery_latency_minutes is not None and last_recovery_latency_minutes < 0:
        last_recovery_latency_minutes = None
    window_open = _coerce_optional_bool(lifecycle_summary.get("window_open")) is True

    if (
        lifecycle_state == "escalated"
        and priority_hint == "high_priority_backlog_present"
        and active_high_priority_unresolved_count > 0
    ):
        intervention_status = "intervention_required"
        intervention_required = True
        intervention_priority = "high"
        intervention_reason = "high_priority_unresolved_escalation_backlog"
    elif lifecycle_state == "escalated":
        intervention_status = "intervention_required"
        intervention_required = True
        intervention_priority = "warning"
        intervention_reason = "unresolved_escalation_window_open"
    elif hint_consistency_severity == "high":
        intervention_status = "attention_required"
        intervention_required = False
        intervention_priority = "warning"
        intervention_reason = "conflicting_runtime_and_lifecycle_hints"
    elif lifecycle_state in {"recovering", "retrial_window_open"}:
        intervention_status = "monitor"
        intervention_required = False
        intervention_priority = "warning"
        intervention_reason = lifecycle_reason
    elif lifecycle_state == "steady":
        intervention_status = "ready"
        intervention_required = False
        intervention_priority = "info"
        intervention_reason = lifecycle_reason
    else:
        intervention_status = "unknown"
        intervention_required = False
        intervention_priority = "info"
        intervention_reason = lifecycle_reason

    return {
        "available": True,
        "intervention_status": intervention_status,
        "intervention_required": intervention_required,
        "intervention_priority": intervention_priority,
        "intervention_reason": intervention_reason,
        "preferred_operator_action_hint": preferred_operator_action_hint,
        "suggested_mode": suggested_mode,
        "lifecycle_state": lifecycle_state,
        "window_open": window_open,
        "active_high_priority_unresolved_count": active_high_priority_unresolved_count,
        "hint_consistency_status": hint_consistency_status,
        "hint_consistency_severity": hint_consistency_severity,
        "resolution_trend_available": resolution_trend_available,
        "recent_unresolved_count": recent_unresolved_count,
        "recent_resolution_rate": recent_resolution_rate,
        "recovery_latency_available": recovery_latency_available,
        "last_recovery_latency_minutes": last_recovery_latency_minutes,
    }


def _hybrid_collection_operator_intervention_stability_summary(
    intervention_trend_summary: dict[str, Any],
) -> dict[str, Any]:
    intervention_trend_summary = _coerce_optional_mapping(intervention_trend_summary)
    if _coerce_optional_bool(intervention_trend_summary.get("available")) is not True:
        return {
            "available": False,
            "stability_status": "unknown",
            "stability_severity": "info",
            "current_intervention_status": None,
            "previous_intervention_status": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": None,
            "stability_action_hint": None,
        }

    current_status = _coerce_optional_text(
        intervention_trend_summary.get("current_intervention_status")
    )
    previous_status = _coerce_optional_text(
        intervention_trend_summary.get("previous_distinct_intervention_status")
    )
    recent_change_count = (
        _coerce_optional_int(intervention_trend_summary.get("recent_change_count")) or 0
    )
    if recent_change_count < 0:
        recent_change_count = 0
    last_change_at = _coerce_optional_text(
        intervention_trend_summary.get("last_change_at")
    )

    if (
        current_status == "intervention_required"
        and recent_change_count > 0
        and previous_status
    ):
        stability_status = "escalating"
        stability_severity = "high"
        operator_readable_explanation = f"Intervention escalated from {previous_status} to intervention_required recently."
        stability_action_hint = "prefer browser and investigate escalating intervention"
    elif current_status == "ready" and recent_change_count == 0:
        stability_status = "stable_ready"
        stability_severity = "info"
        operator_readable_explanation = (
            "Intervention remains ready with no recent status changes."
        )
        stability_action_hint = "keep hybrid and continue monitoring"
    elif current_status == "intervention_required" and recent_change_count == 0:
        stability_status = "persistent_intervention_required"
        stability_severity = "high"
        operator_readable_explanation = (
            "Intervention remains required with no recent status changes."
        )
        stability_action_hint = (
            "treat as sustained intervention and investigate backlog"
        )
    elif recent_change_count >= 2:
        stability_status = "flapping"
        stability_severity = "warning"
        operator_readable_explanation = (
            "Intervention status changed multiple times recently."
        )
        stability_action_hint = (
            "pause automation and inspect instability before resuming"
        )
    else:
        stability_status = "transitioning"
        stability_severity = "warning"
        operator_readable_explanation = (
            f"Intervention is transitioning and currently in {current_status}."
            if current_status is not None
            else "Intervention is transitioning."
        )
        stability_action_hint = (
            "monitor until stable before resuming aggressive intervention"
        )

    return {
        "available": True,
        "stability_status": stability_status,
        "stability_severity": stability_severity,
        "current_intervention_status": current_status,
        "previous_intervention_status": previous_status,
        "recent_change_count": recent_change_count,
        "last_change_at": last_change_at,
        "operator_readable_explanation": operator_readable_explanation,
        "stability_action_hint": stability_action_hint,
    }


__all__ = [
    "_hybrid_collection_lifecycle_state_summary",
    "_hybrid_collection_action_hint_consistency_summary",
    "_hybrid_collection_operator_intervention_policy_summary",
    "_hybrid_collection_operator_intervention_stability_summary",
]
