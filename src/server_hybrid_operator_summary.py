from __future__ import annotations

from pathlib import Path
from typing import Any

from src.server_hybrid_overview import (
    _hybrid_collection_operator_action_hint_trend_overview_fields,
    _hybrid_collection_operator_digest_stability_overview_fields,
    _hybrid_collection_operator_digest_trend_overview_fields,
    _hybrid_collection_operator_final_guidance_stability_overview_fields,
    _hybrid_collection_operator_final_guidance_trend_overview_fields,
    _hybrid_collection_operator_history_overview_fields,
    _hybrid_collection_operator_intervention_event_overview_fields,
    _hybrid_collection_operator_intervention_stability_overview_fields,
    _hybrid_collection_operator_intervention_trend_overview_fields,
    _hybrid_collection_operator_overview_fields,
)
from src.status_snapshot_values import (
    _coerce_optional_bool,
    _coerce_optional_mapping,
    _coerce_optional_text,
    _load_jsonl_snapshots,
)
from src.utc_timestamps import _parse_utc_timestamp, _utc_timestamp_leq


def _hybrid_collection_operator_final_guidance_summary(
    intervention_policy_summary: dict[str, Any],
    intervention_stability_summary: dict[str, Any],
) -> dict[str, Any]:
    intervention_policy_summary = _coerce_optional_mapping(intervention_policy_summary)
    intervention_stability_summary = _coerce_optional_mapping(
        intervention_stability_summary
    )
    available = (
        _coerce_optional_bool(intervention_policy_summary.get("available")) is True
        or _coerce_optional_bool(intervention_stability_summary.get("available"))
        is True
    )
    if not available:
        return {
            "available": False,
            "guidance_label": None,
            "guidance_priority": None,
            "guidance_message": None,
            "preferred_action_hint": None,
            "suggested_mode": None,
            "intervention_status": None,
            "stability_status": None,
        }

    stability_status = (
        _coerce_optional_text(intervention_stability_summary.get("stability_status"))
        or ""
    )
    action_hint = (
        _coerce_optional_text(
            intervention_stability_summary.get("stability_action_hint")
        )
        or ""
    )
    intervention_status = _coerce_optional_text(
        intervention_stability_summary.get("current_intervention_status")
    ) or _coerce_optional_text(intervention_policy_summary.get("intervention_status"))
    suggested_mode = _coerce_optional_text(
        intervention_policy_summary.get("suggested_mode")
    )
    normalized_action_hint = action_hint.lower()
    if "browser" in normalized_action_hint and stability_status in {
        "escalating",
        "persistent_intervention_required",
    }:
        suggested_mode = "browser"
    elif "hybrid" in normalized_action_hint and not suggested_mode:
        suggested_mode = "hybrid"

    guidance_priority: str | None
    if stability_status == "escalating":
        guidance_label = "Escalating intervention"
        guidance_priority = "high"
    elif stability_status == "persistent_intervention_required":
        guidance_label = "Persistent intervention required"
        guidance_priority = "high"
    elif stability_status == "flapping":
        guidance_label = "Flapping intervention"
        guidance_priority = "warning"
    elif stability_status == "transitioning":
        guidance_label = "Transitioning intervention"
        guidance_priority = "warning"
    elif stability_status == "stable_ready":
        guidance_label = "Stable ready state"
        guidance_priority = "info"
    else:
        guidance_label = "Operator guidance"
        guidance_priority = _coerce_optional_text(
            intervention_policy_summary.get("intervention_priority")
        )

    guidance_message = (
        f"{guidance_label}: {action_hint}." if action_hint else guidance_label
    )
    return {
        "available": True,
        "guidance_label": guidance_label,
        "guidance_priority": guidance_priority,
        "guidance_message": guidance_message,
        "preferred_action_hint": action_hint or None,
        "suggested_mode": suggested_mode,
        "intervention_status": intervention_status,
        "stability_status": stability_status or None,
    }


def _hybrid_collection_operator_digest_summary(
    intervention_policy_summary: dict[str, Any],
    intervention_stability_summary: dict[str, Any],
    final_guidance_summary: dict[str, Any],
    final_guidance_stability_summary: dict[str, Any],
) -> dict[str, Any]:
    intervention_policy_summary = _coerce_optional_mapping(intervention_policy_summary)
    intervention_stability_summary = _coerce_optional_mapping(
        intervention_stability_summary
    )
    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
    final_guidance_stability_summary = _coerce_optional_mapping(
        final_guidance_stability_summary
    )
    available = any(
        (
            _coerce_optional_bool(intervention_policy_summary.get("available")) is True,
            _coerce_optional_bool(intervention_stability_summary.get("available"))
            is True,
            _coerce_optional_bool(final_guidance_summary.get("available")) is True,
            _coerce_optional_bool(final_guidance_stability_summary.get("available"))
            is True,
        )
    )
    if not available:
        return {
            "available": False,
            "digest_status": "unknown",
            "digest_priority": "info",
            "final_guidance_message": None,
            "intervention_status": None,
            "intervention_stability_status": None,
            "final_guidance_stability_status": None,
            "operator_digest_message": None,
        }

    current_guidance_label = _coerce_optional_text(
        final_guidance_stability_summary.get("current_guidance_label")
    ) or _coerce_optional_text(final_guidance_summary.get("guidance_label"))
    current_guidance_priority = _coerce_optional_text(
        final_guidance_stability_summary.get("current_guidance_priority")
    ) or _coerce_optional_text(final_guidance_summary.get("guidance_priority"))
    current_guidance_message = _coerce_optional_text(
        final_guidance_stability_summary.get("current_guidance_message")
    ) or _coerce_optional_text(final_guidance_summary.get("guidance_message"))
    if not current_guidance_priority:
        if current_guidance_label in {
            "Escalating intervention",
            "Persistent intervention required",
        }:
            current_guidance_priority = "high"
        elif current_guidance_label in {
            "Transitioning intervention",
            "Flapping intervention",
        }:
            current_guidance_priority = "warning"
        elif current_guidance_label == "Stable ready state":
            current_guidance_priority = "info"
    intervention_status = _coerce_optional_text(
        intervention_policy_summary.get("intervention_status")
    )
    intervention_stability_status = _coerce_optional_text(
        intervention_stability_summary.get("stability_status")
    )
    final_guidance_stability_status = _coerce_optional_text(
        final_guidance_stability_summary.get("stability_status")
    )
    final_guidance_priority = (
        _coerce_optional_text(current_guidance_priority)
        or _coerce_optional_text(
            final_guidance_stability_summary.get("stability_severity")
        )
        or "info"
    )

    guidance_intervention_status = None
    guidance_intervention_stability_status = None
    if current_guidance_label == "Stable ready state":
        guidance_intervention_status = "ready"
        guidance_intervention_stability_status = "stable_ready"
    elif current_guidance_label == "Transitioning intervention":
        guidance_intervention_status = "monitor"
        guidance_intervention_stability_status = "transitioning"
    elif current_guidance_label == "Escalating intervention":
        guidance_intervention_status = "intervention_required"
        guidance_intervention_stability_status = "escalating"
    elif current_guidance_label == "Persistent intervention required":
        guidance_intervention_status = "intervention_required"
        guidance_intervention_stability_status = "persistent_intervention_required"
    elif current_guidance_label == "Flapping intervention":
        guidance_intervention_status = "monitor"
        guidance_intervention_stability_status = "flapping"

    if guidance_intervention_status is not None:
        intervention_status = guidance_intervention_status

    if guidance_intervention_stability_status is not None:
        intervention_stability_status = guidance_intervention_stability_status

    if final_guidance_priority == "high":
        digest_status = "intervention_required"
        digest_priority = "high"
    elif final_guidance_priority == "warning":
        digest_status = "attention_required"
        digest_priority = "warning"
    else:
        digest_status = "ready"
        digest_priority = "info"

    return {
        "available": True,
        "digest_status": digest_status,
        "digest_priority": digest_priority,
        "final_guidance_message": current_guidance_message,
        "intervention_status": intervention_status or current_guidance_label,
        "intervention_stability_status": intervention_stability_status,
        "final_guidance_stability_status": final_guidance_stability_status,
        "operator_digest_message": current_guidance_message,
    }


def _hybrid_collection_recovery_latency_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    escalation_entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_operator_escalation_events.jsonl"
    )
    recovery_entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    )
    if not escalation_entries or not recovery_entries:
        return {
            "available": False,
            "last_recovery_at": None,
            "last_recovery_from_policy_status": None,
            "last_recovery_to_policy_status": None,
            "matched_escalation_at": None,
            "matched_escalation_policy_status": None,
            "last_recovery_latency_seconds": None,
            "last_recovery_latency_minutes": None,
        }

    recent_escalations = escalation_entries[-limit:]
    recent_recoveries = recovery_entries[-limit:]
    last_recovery = recent_recoveries[-1]
    recovery_at = _coerce_optional_text(last_recovery.get("generated_at"))
    matched_escalation = None
    matched_escalation_at = None
    for entry in reversed(recent_escalations):
        escalation_at = _coerce_optional_text(entry.get("generated_at"))
        if (
            escalation_at
            and recovery_at
            and _utc_timestamp_leq(escalation_at, recovery_at)
        ):
            matched_escalation = entry
            matched_escalation_at = escalation_at
            break
    if matched_escalation is None:
        return {
            "available": False,
            "last_recovery_at": recovery_at,
            "last_recovery_from_policy_status": _coerce_optional_text(
                last_recovery.get("from_policy_status")
            ),
            "last_recovery_to_policy_status": _coerce_optional_text(
                last_recovery.get("to_policy_status")
            ),
            "matched_escalation_at": None,
            "matched_escalation_policy_status": None,
            "last_recovery_latency_seconds": None,
            "last_recovery_latency_minutes": None,
        }

    latency_seconds = None
    latency_minutes = None
    try:
        recovery_dt = _parse_utc_timestamp(recovery_at)
        escalation_dt = _parse_utc_timestamp(matched_escalation_at)
        if recovery_dt is None or escalation_dt is None:
            raise ValueError("invalid hybrid timestamp")
        latency_seconds = int((recovery_dt - escalation_dt).total_seconds())
        latency_minutes = round(latency_seconds / 60, 2)
        if latency_seconds < 0:
            latency_seconds = None
            latency_minutes = None
    except Exception:
        latency_seconds = None
        latency_minutes = None

    return {
        "available": True,
        "last_recovery_at": recovery_at,
        "last_recovery_from_policy_status": _coerce_optional_text(
            last_recovery.get("from_policy_status")
        ),
        "last_recovery_to_policy_status": _coerce_optional_text(
            last_recovery.get("to_policy_status")
        ),
        "matched_escalation_at": matched_escalation_at,
        "matched_escalation_policy_status": _coerce_optional_text(
            matched_escalation.get("policy_status")
        ),
        "last_recovery_latency_seconds": latency_seconds,
        "last_recovery_latency_minutes": latency_minutes,
    }


__all__ = [
    "_hybrid_collection_operator_final_guidance_summary",
    "_hybrid_collection_operator_digest_summary",
    "_hybrid_collection_recovery_latency_summary",
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
]
