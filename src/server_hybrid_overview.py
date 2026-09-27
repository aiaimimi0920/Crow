"""Project hybrid summaries into the public collection overview fields."""

from __future__ import annotations

from collections.abc import Mapping

from src.status_snapshot_values import (
    _coerce_optional_bool,
    _coerce_optional_float,
    _coerce_optional_int,
    _coerce_optional_text,
)


def _hybrid_collection_operator_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    guidance_applied_count = (
        _coerce_optional_int(summary.get("guidance_applied_count")) or 0
    )
    if guidance_applied_count < 0:
        guidance_applied_count = 0
    browserless_success_count = (
        _coerce_optional_int(summary.get("browserless_success_count")) or 0
    )
    if browserless_success_count < 0:
        browserless_success_count = 0
    browser_fallback_required_count = (
        _coerce_optional_int(summary.get("browser_fallback_required_count")) or 0
    )
    if browser_fallback_required_count < 0:
        browser_fallback_required_count = 0
    browser_worker_dispatched_count = (
        _coerce_optional_int(summary.get("browser_worker_dispatched_count")) or 0
    )
    if browser_worker_dispatched_count < 0:
        browser_worker_dispatched_count = 0
    last_task_page = _coerce_optional_int(summary.get("last_task_page"))
    if last_task_page is not None and last_task_page < 0:
        last_task_page = None
    return {
        "hybrid_collection_available": _coerce_optional_bool(summary.get("available"))
        is True,
        "hybrid_collection_runner_mode": _coerce_optional_text(
            summary.get("runner_mode")
        ),
        "hybrid_collection_requested_mode": _coerce_optional_text(
            summary.get("requested_mode")
        ),
        "hybrid_collection_effective_mode_source": _coerce_optional_text(
            summary.get("effective_mode_source")
        ),
        "hybrid_collection_operator_action_hint": _coerce_optional_text(
            summary.get("operator_action_hint")
        ),
        "hybrid_collection_last_decision": _coerce_optional_text(
            summary.get("last_decision")
        ),
        "hybrid_collection_last_reason": _coerce_optional_text(
            summary.get("last_reason")
        ),
        "hybrid_collection_last_effective_mode": _coerce_optional_text(
            summary.get("last_effective_mode")
        ),
        "hybrid_collection_top_fallback_reason": _coerce_optional_text(
            summary.get("top_fallback_reason")
        ),
        "hybrid_collection_termination_reason": _coerce_optional_text(
            summary.get("termination_reason")
        ),
        "hybrid_collection_guidance_applied_count": guidance_applied_count,
        "hybrid_collection_guidance_status": _coerce_optional_text(
            summary.get("guidance_status")
        ),
        "hybrid_collection_recovery_policy_status": _coerce_optional_text(
            summary.get("recovery_policy_status")
        ),
        "hybrid_collection_recovery_mode_pin_active": _coerce_optional_bool(
            summary.get("recovery_policy_mode_pin_active")
        )
        is True,
        "hybrid_collection_browserless_success_count": browserless_success_count,
        "hybrid_collection_browser_fallback_required_count": browser_fallback_required_count,
        "hybrid_collection_browser_worker_dispatched_count": browser_worker_dispatched_count,
        "hybrid_collection_last_task_url": _coerce_optional_text(
            summary.get("last_task_url")
        ),
        "hybrid_collection_last_task_page": last_task_page,
        "hybrid_collection_last_submit_batch_status": _coerce_optional_text(
            summary.get("last_submit_batch_status")
        ),
        "hybrid_collection_last_submit_progress_status": _coerce_optional_text(
            summary.get("last_submit_progress_status")
        ),
    }


def _hybrid_collection_operator_history_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_runs = _coerce_optional_int(summary.get("recent_runs")) or 0
    if recent_runs < 0:
        recent_runs = 0
    recent_browserless_success_count = (
        _coerce_optional_int(summary.get("recent_browserless_success_count")) or 0
    )
    if recent_browserless_success_count < 0:
        recent_browserless_success_count = 0
    recent_browser_fallback_required_count = (
        _coerce_optional_int(summary.get("recent_browser_fallback_required_count")) or 0
    )
    if recent_browser_fallback_required_count < 0:
        recent_browser_fallback_required_count = 0
    recent_browser_worker_dispatched_count = (
        _coerce_optional_int(summary.get("recent_browser_worker_dispatched_count")) or 0
    )
    if recent_browser_worker_dispatched_count < 0:
        recent_browser_worker_dispatched_count = 0
    recent_browserless_success_rate = (
        _coerce_optional_float(summary.get("recent_browserless_success_rate")) or 0.0
    )
    if recent_browserless_success_rate < 0:
        recent_browserless_success_rate = 0.0
    elif recent_browserless_success_rate > 1:
        recent_browserless_success_rate = 1.0
    return {
        "hybrid_collection_recent_runs": recent_runs,
        "hybrid_collection_recent_browserless_success_count": recent_browserless_success_count,
        "hybrid_collection_recent_browser_fallback_required_count": recent_browser_fallback_required_count,
        "hybrid_collection_recent_browser_worker_dispatched_count": recent_browser_worker_dispatched_count,
        "hybrid_collection_recent_browserless_success_rate": recent_browserless_success_rate,
        "hybrid_collection_recent_top_fallback_reason": _coerce_optional_text(
            summary.get("recent_top_fallback_reason")
        ),
        "hybrid_collection_recent_top_termination_reason": _coerce_optional_text(
            summary.get("recent_top_termination_reason")
        ),
    }


def _hybrid_collection_operator_action_hint_trend_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    return {
        "hybrid_collection_current_action_hint": _coerce_optional_text(
            summary.get("current_action_hint")
        ),
        "hybrid_collection_previous_action_hint": _coerce_optional_text(
            summary.get("previous_distinct_action_hint")
        ),
        "hybrid_collection_action_hint_change_count": recent_change_count,
        "hybrid_collection_action_hint_last_changed_at": _coerce_optional_text(
            summary.get("last_change_at")
        ),
    }


def _hybrid_collection_operator_final_guidance_trend_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    return {
        "hybrid_collection_current_final_guidance_label": _coerce_optional_text(
            summary.get("current_guidance_label")
        ),
        "hybrid_collection_current_final_guidance_priority": _coerce_optional_text(
            summary.get("current_guidance_priority")
        ),
        "hybrid_collection_current_final_guidance_message": _coerce_optional_text(
            summary.get("current_guidance_message")
        ),
        "hybrid_collection_previous_final_guidance_message": _coerce_optional_text(
            summary.get("previous_distinct_guidance_message")
        ),
        "hybrid_collection_final_guidance_change_count": recent_change_count,
        "hybrid_collection_final_guidance_last_changed_at": _coerce_optional_text(
            summary.get("last_change_at")
        ),
    }


def _hybrid_collection_operator_final_guidance_stability_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    return {
        "hybrid_collection_final_guidance_stability_status": _coerce_optional_text(
            summary.get("stability_status")
        ),
        "hybrid_collection_final_guidance_stability_severity": _coerce_optional_text(
            summary.get("stability_severity")
        ),
        "hybrid_collection_final_guidance_stability_explanation": _coerce_optional_text(
            summary.get("operator_readable_explanation")
        ),
    }


def _hybrid_collection_operator_digest_trend_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    return {
        "hybrid_collection_current_digest_status": _coerce_optional_text(
            summary.get("current_digest_status")
        ),
        "hybrid_collection_current_digest_priority": _coerce_optional_text(
            summary.get("current_digest_priority")
        ),
        "hybrid_collection_current_digest_message": _coerce_optional_text(
            summary.get("current_digest_message")
        ),
        "hybrid_collection_previous_digest_message": _coerce_optional_text(
            summary.get("previous_distinct_digest_message")
        ),
        "hybrid_collection_digest_change_count": recent_change_count,
        "hybrid_collection_digest_last_changed_at": _coerce_optional_text(
            summary.get("last_change_at")
        ),
    }


def _hybrid_collection_operator_digest_stability_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    return {
        "hybrid_collection_digest_stability_status": _coerce_optional_text(
            summary.get("stability_status")
        ),
        "hybrid_collection_digest_stability_severity": _coerce_optional_text(
            summary.get("stability_severity")
        ),
        "hybrid_collection_digest_stability_explanation": _coerce_optional_text(
            summary.get("operator_readable_explanation")
        ),
    }


def _hybrid_collection_operator_intervention_trend_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count")) or 0
    if recent_change_count < 0:
        recent_change_count = 0
    return {
        "hybrid_collection_current_intervention_status": _coerce_optional_text(
            summary.get("current_intervention_status")
        ),
        "hybrid_collection_current_intervention_priority": _coerce_optional_text(
            summary.get("current_intervention_priority")
        ),
        "hybrid_collection_current_intervention_reason": _coerce_optional_text(
            summary.get("current_intervention_reason")
        ),
        "hybrid_collection_previous_intervention_status": _coerce_optional_text(
            summary.get("previous_distinct_intervention_status")
        ),
        "hybrid_collection_intervention_change_count": recent_change_count,
        "hybrid_collection_intervention_last_changed_at": _coerce_optional_text(
            summary.get("last_change_at")
        ),
    }


def _hybrid_collection_operator_intervention_event_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_event_count = _coerce_optional_int(summary.get("recent_event_count")) or 0
    if recent_event_count < 0:
        recent_event_count = 0
    return {
        "hybrid_collection_recent_intervention_event_count": recent_event_count,
        "hybrid_collection_last_intervention_event_at": _coerce_optional_text(
            summary.get("last_event_at")
        ),
        "hybrid_collection_last_intervention_transition_kind": _coerce_optional_text(
            summary.get("last_transition_kind")
        ),
        "hybrid_collection_last_to_intervention_status": _coerce_optional_text(
            summary.get("last_to_intervention_status")
        ),
        "hybrid_collection_last_to_intervention_priority": _coerce_optional_text(
            summary.get("last_to_intervention_priority")
        ),
        "hybrid_collection_last_to_final_guidance_label": _coerce_optional_text(
            summary.get("last_to_final_guidance_label")
        ),
        "hybrid_collection_last_to_final_guidance_priority": _coerce_optional_text(
            summary.get("last_to_final_guidance_priority")
        ),
        "hybrid_collection_last_to_final_guidance_message": _coerce_optional_text(
            summary.get("last_to_final_guidance_message")
        ),
    }


def _hybrid_collection_operator_intervention_stability_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    return {
        "hybrid_collection_intervention_stability_status": _coerce_optional_text(
            summary.get("stability_status")
        ),
        "hybrid_collection_intervention_stability_severity": _coerce_optional_text(
            summary.get("stability_severity")
        ),
        "hybrid_collection_intervention_stability_explanation": _coerce_optional_text(
            summary.get("operator_readable_explanation")
        ),
        "hybrid_collection_intervention_stability_action_hint": _coerce_optional_text(
            summary.get("stability_action_hint")
        ),
    }


def _hybrid_collection_operator_intervention_policy_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    return {
        "hybrid_collection_operator_intervention_status": _coerce_optional_text(
            summary.get("intervention_status")
        ),
        "hybrid_collection_operator_intervention_required": _coerce_optional_bool(
            summary.get("intervention_required")
        )
        is True,
        "hybrid_collection_operator_intervention_priority": _coerce_optional_text(
            summary.get("intervention_priority")
        ),
        "hybrid_collection_operator_intervention_reason": _coerce_optional_text(
            summary.get("intervention_reason")
        ),
        "hybrid_collection_operator_intervention_action_hint": _coerce_optional_text(
            summary.get("preferred_operator_action_hint")
        ),
        "hybrid_collection_operator_intervention_suggested_mode": _coerce_optional_text(
            summary.get("suggested_mode")
        ),
    }


def _hybrid_collection_operator_final_guidance_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    return {
        "hybrid_collection_operator_final_guidance_label": _coerce_optional_text(
            summary.get("guidance_label")
        ),
        "hybrid_collection_operator_final_guidance_priority": _coerce_optional_text(
            summary.get("guidance_priority")
        ),
        "hybrid_collection_operator_final_guidance_message": _coerce_optional_text(
            summary.get("guidance_message")
        ),
    }


def _hybrid_collection_operator_digest_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    return {
        "hybrid_collection_operator_digest_status": _coerce_optional_text(
            summary.get("digest_status")
        ),
        "hybrid_collection_operator_digest_priority": _coerce_optional_text(
            summary.get("digest_priority")
        ),
        "hybrid_collection_operator_digest_message": _coerce_optional_text(
            summary.get("operator_digest_message")
        ),
    }


def _hybrid_collection_operator_guidance_overview_fields(
    guidance: Mapping[str, object],
) -> dict[str, object]:
    return {
        "hybrid_collection_guidance_status": _coerce_optional_text(
            guidance.get("guidance_status")
        ),
        "hybrid_collection_guidance_priority": _coerce_optional_text(
            guidance.get("priority")
        ),
        "hybrid_collection_recommended_mode": _coerce_optional_text(
            guidance.get("recommended_mode")
        ),
        "hybrid_collection_top_guidance_reason": _coerce_optional_text(
            guidance.get("top_guidance_reason")
        ),
    }


def _hybrid_collection_operator_mode_switch_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_switch_count = _coerce_optional_int(summary.get("recent_switch_count")) or 0
    if recent_switch_count < 0:
        recent_switch_count = 0
    return {
        "hybrid_collection_recent_mode_switch_count": recent_switch_count,
        "hybrid_collection_top_switch_target_mode": _coerce_optional_text(
            summary.get("top_target_mode")
        ),
        "hybrid_collection_top_switch_guidance_reason": _coerce_optional_text(
            summary.get("top_guidance_reason")
        ),
    }


def _hybrid_collection_operator_recovery_policy_overview_fields(
    policy: Mapping[str, object],
) -> dict[str, object]:
    budget_remaining = (
        _coerce_optional_int(policy.get("hybrid_retrial_budget_remaining")) or 0
    )
    if budget_remaining < 0:
        budget_remaining = 0
    return {
        "hybrid_collection_recovery_policy_status": _coerce_optional_text(
            policy.get("policy_status")
        ),
        "hybrid_collection_recovery_policy_priority": _coerce_optional_text(
            policy.get("priority")
        ),
        "hybrid_collection_recovery_effective_mode": _coerce_optional_text(
            policy.get("effective_recommended_mode")
        ),
        "hybrid_collection_recovery_mode_pin_active": _coerce_optional_bool(
            policy.get("mode_pin_active")
        )
        is True,
        "hybrid_collection_recovery_top_policy_reason": _coerce_optional_text(
            policy.get("top_policy_reason")
        ),
        "hybrid_collection_recovery_budget_remaining": budget_remaining,
        "hybrid_collection_recovery_last_transition_kind": _coerce_optional_text(
            policy.get("last_recovery_transition_kind")
        ),
    }


def _hybrid_collection_operator_recovery_policy_event_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_transition_count = (
        _coerce_optional_int(summary.get("recent_transition_count")) or 0
    )
    if recent_transition_count < 0:
        recent_transition_count = 0
    return {
        "hybrid_collection_recent_recovery_policy_transition_count": recent_transition_count,
        "hybrid_collection_last_recovery_transition_kind": _coerce_optional_text(
            summary.get("last_transition_kind")
        ),
        "hybrid_collection_last_recovery_to_policy_status": _coerce_optional_text(
            summary.get("last_to_policy_status")
        ),
    }


def _hybrid_collection_operator_escalation_event_overview_fields(
    summary: Mapping[str, object],
) -> dict[str, object]:
    recent_event_count = _coerce_optional_int(summary.get("recent_event_count")) or 0
    if recent_event_count < 0:
        recent_event_count = 0
    return {
        "hybrid_collection_recent_operator_escalation_count": recent_event_count,
        "hybrid_collection_top_operator_escalation_kind": _coerce_optional_text(
            summary.get("top_escalation_kind")
        ),
        "hybrid_collection_top_operator_escalation_source": _coerce_optional_text(
            summary.get("top_operator_escalation_source")
        ),
        "hybrid_collection_top_operator_escalation_policy_status": _coerce_optional_text(
            summary.get("top_policy_status")
        ),
        "hybrid_collection_last_operator_escalation_source": _coerce_optional_text(
            summary.get("last_operator_escalation_source")
        ),
        "hybrid_collection_last_operator_escalation_audit_message": _coerce_optional_text(
            summary.get("last_operator_escalation_audit_message")
        ),
    }


__all__ = [
    "_hybrid_collection_operator_overview_fields",
    "_hybrid_collection_operator_history_overview_fields",
    "_hybrid_collection_operator_action_hint_trend_overview_fields",
    "_hybrid_collection_operator_final_guidance_trend_overview_fields",
    "_hybrid_collection_operator_final_guidance_stability_overview_fields",
    "_hybrid_collection_operator_digest_trend_overview_fields",
    "_hybrid_collection_operator_digest_stability_overview_fields",
    "_hybrid_collection_operator_intervention_trend_overview_fields",
    "_hybrid_collection_operator_intervention_event_overview_fields",
    "_hybrid_collection_operator_intervention_stability_overview_fields",
    "_hybrid_collection_operator_intervention_policy_overview_fields",
    "_hybrid_collection_operator_final_guidance_overview_fields",
    "_hybrid_collection_operator_digest_overview_fields",
    "_hybrid_collection_operator_guidance_overview_fields",
    "_hybrid_collection_operator_mode_switch_overview_fields",
    "_hybrid_collection_operator_recovery_policy_overview_fields",
    "_hybrid_collection_operator_recovery_policy_event_overview_fields",
    "_hybrid_collection_operator_escalation_event_overview_fields",
]
