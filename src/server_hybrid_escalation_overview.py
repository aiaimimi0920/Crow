"""Public overview projections for escalation and recovery lifecycle summaries."""

from __future__ import annotations

from collections.abc import Mapping

from src.status_snapshot_values import (
    _coerce_optional_bool,
    _coerce_optional_float,
    _coerce_optional_int,
    _coerce_optional_text,
)


def _hybrid_collection_operator_escalation_event_trend_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_source_change_count = (
        _coerce_optional_int(summary.get("recent_source_change_count")) or 0
    )
    if recent_source_change_count < 0:
        recent_source_change_count = 0
    return {
        "hybrid_collection_current_operator_escalation_source": _coerce_optional_text(
            summary.get("current_operator_escalation_source")
        ),
        "hybrid_collection_previous_operator_escalation_source": _coerce_optional_text(
            summary.get("previous_distinct_operator_escalation_source")
        ),
        "hybrid_collection_operator_escalation_source_change_count": recent_source_change_count,
        "hybrid_collection_operator_escalation_source_last_changed_at": _coerce_optional_text(
            summary.get("last_source_change_at")
        ),
    }


def _hybrid_collection_operator_escalation_event_stability_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    return {
        "hybrid_collection_operator_escalation_source_stability_status": _coerce_optional_text(
            summary.get("stability_status")
        ),
        "hybrid_collection_operator_escalation_source_stability_severity": _coerce_optional_text(
            summary.get("stability_severity")
        ),
        "hybrid_collection_operator_escalation_source_stability_explanation": _coerce_optional_text(
            summary.get("operator_readable_explanation")
        ),
    }


def _hybrid_collection_operator_escalation_recovery_event_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_recovery_count = (
        _coerce_optional_int(summary.get("recent_recovery_count")) or 0
    )
    if recent_recovery_count < 0:
        recent_recovery_count = 0
    return {
        "hybrid_collection_recent_operator_escalation_recovery_count": recent_recovery_count,
        "hybrid_collection_last_operator_escalation_recovery_policy_status": _coerce_optional_text(
            summary.get("last_to_policy_status")
        ),
    }


def _hybrid_collection_operator_unresolved_escalation_window_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    window_open = _coerce_optional_bool(summary.get("window_open")) is True
    duration_seconds = _coerce_optional_int(
        summary.get("current_window_duration_seconds")
    )
    if duration_seconds is not None and duration_seconds < 0:
        duration_seconds = None
    duration_minutes = _coerce_optional_float(
        summary.get("current_window_duration_minutes")
    )
    if duration_minutes is not None and duration_minutes < 0:
        duration_minutes = None
    return {
        "hybrid_collection_unresolved_escalation_window_open": window_open,
        "hybrid_collection_unresolved_escalation_policy_status": (
            _coerce_optional_text(summary.get("last_escalation_policy_status"))
            if window_open
            else _coerce_optional_text(summary.get("last_recovery_to_policy_status"))
        ),
        "hybrid_collection_unresolved_escalation_last_event_at": (
            _coerce_optional_text(summary.get("last_escalation_at"))
            if window_open
            else _coerce_optional_text(summary.get("last_recovery_at"))
        ),
        "hybrid_collection_unresolved_escalation_duration_seconds": duration_seconds,
        "hybrid_collection_unresolved_escalation_duration_minutes": duration_minutes,
    }


def _hybrid_collection_operator_lifecycle_state_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    active_high_priority_unresolved_count = _coerce_optional_int(
        summary.get("active_high_priority_unresolved_count")
    )
    if (
        active_high_priority_unresolved_count is None
        or active_high_priority_unresolved_count < 0
    ):
        active_high_priority_unresolved_count = 0
    return {
        "hybrid_collection_lifecycle_state": _coerce_optional_text(
            summary.get("lifecycle_state")
        ),
        "hybrid_collection_lifecycle_reason": _coerce_optional_text(
            summary.get("lifecycle_reason")
        ),
        "hybrid_collection_lifecycle_follow_up": _coerce_optional_text(
            summary.get("recommended_follow_up")
        ),
        "hybrid_collection_lifecycle_suggested_mode": _coerce_optional_text(
            summary.get("suggested_mode")
        ),
        "hybrid_collection_lifecycle_action_hint": _coerce_optional_text(
            summary.get("operator_action_hint")
        ),
        "hybrid_collection_lifecycle_priority_hint": _coerce_optional_text(
            summary.get("priority_hint")
        ),
        "hybrid_collection_lifecycle_active_unresolved_priority": _coerce_optional_text(
            summary.get("active_unresolved_priority")
        ),
        "hybrid_collection_lifecycle_active_high_priority_unresolved_count": active_high_priority_unresolved_count,
    }


def _hybrid_collection_operator_action_hint_consistency_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    return {
        "hybrid_collection_action_hint_consistency_status": _coerce_optional_text(
            summary.get("consistency_status")
        ),
        "hybrid_collection_action_hint_hints_match": _coerce_optional_bool(
            summary.get("hints_match")
        )
        is True,
        "hybrid_collection_action_hint_drift_reason": _coerce_optional_text(
            summary.get("drift_reason")
        ),
        "hybrid_collection_action_hint_consistency_severity": _coerce_optional_text(
            summary.get("consistency_severity")
        ),
        "hybrid_collection_action_hint_severity_reason": _coerce_optional_text(
            summary.get("severity_reason")
        ),
        "hybrid_collection_action_hint_source_preference": _coerce_optional_text(
            summary.get("hint_source_preference")
        ),
        "hybrid_collection_action_hint_source_detail": _coerce_optional_text(
            summary.get("preferred_hint_source_detail")
        ),
        "hybrid_collection_action_hint_explanation": _coerce_optional_text(
            summary.get("preferred_hint_explanation")
        ),
        "hybrid_collection_preferred_action_hint": _coerce_optional_text(
            summary.get("preferred_operator_action_hint")
        ),
    }


def _hybrid_collection_operator_recovery_latency_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    latency_seconds = _coerce_optional_int(summary.get("last_recovery_latency_seconds"))
    if latency_seconds is not None and latency_seconds < 0:
        latency_seconds = None
    latency_minutes = _coerce_optional_float(
        summary.get("last_recovery_latency_minutes")
    )
    if latency_minutes is not None and latency_minutes < 0:
        latency_minutes = None
    return {
        "hybrid_collection_last_recovery_latency_seconds": latency_seconds,
        "hybrid_collection_last_recovery_latency_minutes": latency_minutes,
        "hybrid_collection_last_recovery_latency_from_policy_status": _coerce_optional_text(
            summary.get("last_recovery_from_policy_status")
        ),
        "hybrid_collection_last_recovery_latency_to_policy_status": _coerce_optional_text(
            summary.get("last_recovery_to_policy_status")
        ),
    }


def _hybrid_collection_operator_escalation_resolution_trend_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_resolved_count = (
        _coerce_optional_int(summary.get("recent_resolved_count")) or 0
    )
    if recent_resolved_count < 0:
        recent_resolved_count = 0
    recent_unresolved_count = (
        _coerce_optional_int(summary.get("recent_unresolved_count")) or 0
    )
    if recent_unresolved_count < 0:
        recent_unresolved_count = 0
    recent_resolution_rate = (
        _coerce_optional_float(summary.get("recent_resolution_rate")) or 0.0
    )
    if recent_resolution_rate < 0:
        recent_resolution_rate = 0.0
    elif recent_resolution_rate > 1:
        recent_resolution_rate = 1.0
    return {
        "hybrid_collection_recent_escalation_resolved_count": recent_resolved_count,
        "hybrid_collection_recent_escalation_unresolved_count": recent_unresolved_count,
        "hybrid_collection_recent_escalation_resolution_rate": recent_resolution_rate,
    }


def _hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_high_priority_escalation_count = (
        _coerce_optional_int(summary.get("recent_high_priority_escalation_count")) or 0
    )
    if recent_high_priority_escalation_count < 0:
        recent_high_priority_escalation_count = 0
    recent_high_priority_resolved_count = (
        _coerce_optional_int(summary.get("recent_high_priority_resolved_count")) or 0
    )
    if recent_high_priority_resolved_count < 0:
        recent_high_priority_resolved_count = 0
    recent_high_priority_unresolved_count = (
        _coerce_optional_int(summary.get("recent_high_priority_unresolved_count")) or 0
    )
    if recent_high_priority_unresolved_count < 0:
        recent_high_priority_unresolved_count = 0
    return {
        "hybrid_collection_recent_high_priority_escalation_count": recent_high_priority_escalation_count,
        "hybrid_collection_recent_high_priority_resolved_count": recent_high_priority_resolved_count,
        "hybrid_collection_recent_high_priority_unresolved_count": recent_high_priority_unresolved_count,
        "hybrid_collection_top_recent_escalation_priority": _coerce_optional_text(
            summary.get("top_recent_escalation_priority")
        ),
        "hybrid_collection_top_recent_unresolved_priority": _coerce_optional_text(
            summary.get("top_recent_unresolved_priority")
        ),
    }


__all__ = [
    "_hybrid_collection_operator_escalation_event_trend_overview_fields",
    "_hybrid_collection_operator_escalation_event_stability_overview_fields",
    "_hybrid_collection_operator_escalation_recovery_event_overview_fields",
    "_hybrid_collection_operator_unresolved_escalation_window_overview_fields",
    "_hybrid_collection_operator_lifecycle_state_overview_fields",
    "_hybrid_collection_operator_action_hint_consistency_overview_fields",
    "_hybrid_collection_operator_recovery_latency_overview_fields",
    "_hybrid_collection_operator_escalation_resolution_trend_overview_fields",
    "_hybrid_collection_operator_escalation_priority_mix_trend_overview_fields",
]
