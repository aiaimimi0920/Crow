from __future__ import annotations

from pathlib import Path
from typing import Any

from src.status_snapshot_values import (
    _coerce_optional_bool,
    _coerce_optional_int,
    _coerce_optional_mapping,
    _coerce_optional_text,
    _load_jsonl_snapshots,
)
from src.utc_timestamps import _parse_utc_timestamp, _utc_now, _utc_timestamp_leq


def _hybrid_collection_operator_escalation_event_stability_summary(
    escalation_event_trend_summary: dict[str, Any],
) -> dict[str, Any]:
    escalation_event_trend_summary = _coerce_optional_mapping(
        escalation_event_trend_summary
    )
    if (
        _coerce_optional_bool(escalation_event_trend_summary.get("available"))
        is not True
    ):
        return {
            "available": False,
            "stability_status": "unknown",
            "stability_severity": "info",
            "current_operator_escalation_source": None,
            "current_escalation_kind": None,
            "current_operator_escalation_audit_message": None,
            "previous_operator_escalation_source": None,
            "recent_source_change_count": 0,
            "last_source_change_at": None,
            "operator_readable_explanation": None,
        }

    current_source = _coerce_optional_text(
        escalation_event_trend_summary.get("current_operator_escalation_source")
    )
    current_kind = _coerce_optional_text(
        escalation_event_trend_summary.get("current_escalation_kind")
    )
    current_audit = _coerce_optional_text(
        escalation_event_trend_summary.get("current_operator_escalation_audit_message")
    )
    previous_source = _coerce_optional_text(
        escalation_event_trend_summary.get(
            "previous_distinct_operator_escalation_source"
        )
    )
    recent_source_change_count = (
        _coerce_optional_int(
            escalation_event_trend_summary.get("recent_source_change_count")
        )
        or 0
    )
    if recent_source_change_count < 0:
        recent_source_change_count = 0
    last_source_change_at = _coerce_optional_text(
        escalation_event_trend_summary.get("last_source_change_at")
    )

    high_sources = {
        "recovery_policy",
        "lifecycle_high_priority_backlog",
        "intervention_stability",
    }

    if recent_source_change_count >= 2:
        stability_status = "source_flapping"
        stability_severity = "warning"
        operator_readable_explanation = (
            "Operator escalation source changed multiple times recently."
        )
    elif recent_source_change_count > 0 and previous_source and current_source:
        stability_status = "source_recently_shifted"
        stability_severity = "high" if current_source in high_sources else "warning"
        operator_readable_explanation = f"Operator escalation source recently shifted from {previous_source} to {current_source}."
    elif current_source == "recovery_policy":
        stability_status = "persistent_recovery_policy_source"
        stability_severity = "high"
        operator_readable_explanation = "Operator escalation source remains recovery_policy with no recent source changes."
    elif current_source == "intervention_stability":
        stability_status = "persistent_intervention_stability_source"
        stability_severity = "high"
        operator_readable_explanation = "Operator escalation source remains intervention_stability with no recent source changes."
    elif current_source == "lifecycle_high_priority_backlog":
        stability_status = "persistent_high_priority_backlog_source"
        stability_severity = "high"
        operator_readable_explanation = "Operator escalation source remains lifecycle_high_priority_backlog with no recent source changes."
    elif current_source:
        stability_status = "stable_escalation_source"
        stability_severity = "warning"
        operator_readable_explanation = f"Operator escalation source remains {current_source} with no recent source changes."
    else:
        stability_status = "source_transitioning"
        stability_severity = "warning"
        operator_readable_explanation = "Operator escalation source is transitioning."

    return {
        "available": True,
        "stability_status": stability_status,
        "stability_severity": stability_severity,
        "current_operator_escalation_source": current_source,
        "current_escalation_kind": current_kind,
        "current_operator_escalation_audit_message": current_audit,
        "previous_operator_escalation_source": previous_source,
        "recent_source_change_count": recent_source_change_count,
        "last_source_change_at": last_source_change_at,
        "operator_readable_explanation": operator_readable_explanation,
    }


def _hybrid_collection_operator_escalation_recovery_event_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    )
    if not entries:
        return {
            "available": False,
            "entry_count": 0,
            "recent_recovery_count": 0,
            "recent_transition_kind_counts": {},
            "recent_to_policy_status_counts": {},
            "top_transition_kind": None,
            "top_to_policy_status": None,
            "last_event_at": None,
            "last_event_session_id": None,
            "last_to_policy_status": None,
        }

    recent_entries = entries[-limit:]
    transition_kind_counts: dict[str, int] = {}
    to_policy_status_counts: dict[str, int] = {}
    for entry in recent_entries:
        transition_kind = _coerce_optional_text(entry.get("transition_kind"))
        if transition_kind:
            transition_kind_counts[transition_kind] = (
                transition_kind_counts.get(transition_kind, 0) + 1
            )
        to_policy_status = _coerce_optional_text(entry.get("to_policy_status"))
        if to_policy_status:
            to_policy_status_counts[to_policy_status] = (
                to_policy_status_counts.get(to_policy_status, 0) + 1
            )

    top_transition_kind = (
        sorted(transition_kind_counts.items(), key=lambda item: (-item[1], item[0]))[0][
            0
        ]
        if transition_kind_counts
        else None
    )
    top_to_policy_status = (
        sorted(to_policy_status_counts.items(), key=lambda item: (-item[1], item[0]))[
            0
        ][0]
        if to_policy_status_counts
        else None
    )
    last_entry = recent_entries[-1]
    return {
        "available": True,
        "entry_count": len(entries),
        "recent_recovery_count": len(recent_entries),
        "recent_transition_kind_counts": transition_kind_counts,
        "recent_to_policy_status_counts": to_policy_status_counts,
        "top_transition_kind": top_transition_kind,
        "top_to_policy_status": top_to_policy_status,
        "last_event_at": _coerce_optional_text(last_entry.get("generated_at")),
        "last_event_session_id": _coerce_optional_text(last_entry.get("session_id")),
        "last_to_policy_status": _coerce_optional_text(
            last_entry.get("to_policy_status")
        ),
    }


def _hybrid_collection_operator_intervention_event_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_operator_intervention_events.jsonl"
    )
    if not entries:
        return {
            "available": False,
            "entry_count": 0,
            "recent_event_count": 0,
            "recent_transition_kind_counts": {},
            "recent_to_intervention_status_counts": {},
            "top_transition_kind": None,
            "top_to_intervention_status": None,
            "last_event_at": None,
            "last_event_session_id": None,
            "last_transition_kind": None,
            "last_to_intervention_status": None,
            "last_to_intervention_priority": None,
            "last_to_final_guidance_label": None,
            "last_to_final_guidance_priority": None,
            "last_to_final_guidance_message": None,
        }

    recent_entries = entries[-limit:]
    transition_kind_counts: dict[str, int] = {}
    to_intervention_status_counts: dict[str, int] = {}
    for entry in recent_entries:
        transition_kind = _coerce_optional_text(entry.get("transition_kind"))
        if transition_kind:
            kind_key = transition_kind
            transition_kind_counts[kind_key] = (
                transition_kind_counts.get(kind_key, 0) + 1
            )
        to_intervention_status = _coerce_optional_text(
            entry.get("to_intervention_status")
        )
        if to_intervention_status:
            status_key = to_intervention_status
            to_intervention_status_counts[status_key] = (
                to_intervention_status_counts.get(status_key, 0) + 1
            )

    top_transition_kind = (
        sorted(transition_kind_counts.items(), key=lambda item: (-item[1], item[0]))[0][
            0
        ]
        if transition_kind_counts
        else None
    )
    top_to_intervention_status = (
        sorted(
            to_intervention_status_counts.items(), key=lambda item: (-item[1], item[0])
        )[0][0]
        if to_intervention_status_counts
        else None
    )
    last_entry = recent_entries[-1]
    return {
        "available": True,
        "entry_count": len(entries),
        "recent_event_count": len(recent_entries),
        "recent_transition_kind_counts": transition_kind_counts,
        "recent_to_intervention_status_counts": to_intervention_status_counts,
        "top_transition_kind": top_transition_kind,
        "top_to_intervention_status": top_to_intervention_status,
        "last_event_at": _coerce_optional_text(last_entry.get("generated_at")),
        "last_event_session_id": _coerce_optional_text(last_entry.get("session_id")),
        "last_transition_kind": _coerce_optional_text(
            last_entry.get("transition_kind")
        ),
        "last_to_intervention_status": _coerce_optional_text(
            last_entry.get("to_intervention_status")
        ),
        "last_to_intervention_priority": _coerce_optional_text(
            last_entry.get("to_intervention_priority")
        ),
        "last_to_final_guidance_label": _coerce_optional_text(
            last_entry.get("to_final_guidance_label")
        ),
        "last_to_final_guidance_priority": _coerce_optional_text(
            last_entry.get("to_final_guidance_priority")
        ),
        "last_to_final_guidance_message": _coerce_optional_text(
            last_entry.get("to_final_guidance_message")
        ),
    }


def _hybrid_collection_unresolved_escalation_window_summary(
    escalation_summary: dict[str, Any],
    recovery_summary: dict[str, Any],
) -> dict[str, Any]:
    escalation_summary = _coerce_optional_mapping(escalation_summary)
    recovery_summary = _coerce_optional_mapping(recovery_summary)
    escalation_available = (
        _coerce_optional_bool(escalation_summary.get("available")) is True
    )
    recovery_available = (
        _coerce_optional_bool(recovery_summary.get("available")) is True
    )
    if not escalation_available and not recovery_available:
        return {
            "available": False,
            "window_status": "no_escalation_history",
            "window_open": False,
            "last_escalation_at": None,
            "last_escalation_policy_status": None,
            "last_recovery_at": None,
            "last_recovery_to_policy_status": None,
            "current_window_duration_seconds": None,
            "current_window_duration_minutes": None,
        }

    last_escalation_at = _coerce_optional_text(escalation_summary.get("last_event_at"))
    last_recovery_at = _coerce_optional_text(recovery_summary.get("last_event_at"))
    last_escalation_policy_status = _coerce_optional_text(
        escalation_summary.get("top_policy_status")
    )
    last_recovery_to_policy_status = _coerce_optional_text(
        recovery_summary.get("last_to_policy_status")
    )
    duration_seconds = None
    duration_minutes = None
    try:
        if last_escalation_at:
            escalation_dt = _parse_utc_timestamp(last_escalation_at)
            if escalation_dt is None:
                raise ValueError("invalid escalation timestamp")
            duration_seconds = int((_utc_now() - escalation_dt).total_seconds())
            duration_minutes = round(duration_seconds / 60, 2)
            if duration_seconds < 0:
                duration_seconds = None
                duration_minutes = None
    except Exception:
        duration_seconds = None
        duration_minutes = None

    if escalation_available and (
        not recovery_available
        or not _utc_timestamp_leq(last_escalation_at, last_recovery_at)
    ):
        return {
            "available": True,
            "window_status": "open",
            "window_open": True,
            "last_escalation_at": last_escalation_at,
            "last_escalation_policy_status": last_escalation_policy_status,
            "last_recovery_at": last_recovery_at,
            "last_recovery_to_policy_status": last_recovery_to_policy_status,
            "current_window_duration_seconds": duration_seconds,
            "current_window_duration_minutes": duration_minutes,
        }

    return {
        "available": True,
        "window_status": "closed",
        "window_open": False,
        "last_escalation_at": last_escalation_at,
        "last_escalation_policy_status": last_escalation_policy_status,
        "last_recovery_at": last_recovery_at,
        "last_recovery_to_policy_status": last_recovery_to_policy_status,
        "current_window_duration_seconds": None,
        "current_window_duration_minutes": None,
    }


def _hybrid_collection_escalation_resolution_trend_summary(
    escalation_summary: dict[str, Any],
    recovery_summary: dict[str, Any],
    unresolved_window_summary: dict[str, Any],
) -> dict[str, Any]:
    escalation_summary = _coerce_optional_mapping(escalation_summary)
    recovery_summary = _coerce_optional_mapping(recovery_summary)
    unresolved_window_summary = _coerce_optional_mapping(unresolved_window_summary)
    escalation_available = (
        _coerce_optional_bool(escalation_summary.get("available")) is True
    )
    recovery_available = (
        _coerce_optional_bool(recovery_summary.get("available")) is True
    )
    if not escalation_available and not recovery_available:
        return {
            "available": False,
            "recent_escalation_count": 0,
            "recent_recovery_count": 0,
            "recent_resolved_count": 0,
            "recent_unresolved_count": 0,
            "recent_resolution_rate": 0.0,
            "window_open": False,
        }

    recent_escalation_count = (
        _coerce_optional_int(escalation_summary.get("recent_event_count")) or 0
    )
    if recent_escalation_count < 0:
        recent_escalation_count = 0
    recent_recovery_count = (
        _coerce_optional_int(recovery_summary.get("recent_recovery_count")) or 0
    )
    if recent_recovery_count < 0:
        recent_recovery_count = 0
    recent_resolved_count = min(recent_escalation_count, recent_recovery_count)
    recent_unresolved_count = max(0, recent_escalation_count - recent_recovery_count)
    resolution_rate = (
        (recent_resolved_count / recent_escalation_count)
        if recent_escalation_count > 0
        else 0.0
    )
    return {
        "available": True,
        "recent_escalation_count": recent_escalation_count,
        "recent_recovery_count": recent_recovery_count,
        "recent_resolved_count": recent_resolved_count,
        "recent_unresolved_count": recent_unresolved_count,
        "recent_resolution_rate": resolution_rate,
        "window_open": _coerce_optional_bool(
            unresolved_window_summary.get("window_open")
        )
        is True,
    }


def _hybrid_collection_escalation_priority_mix_trend_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    escalation_entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_operator_escalation_events.jsonl"
    )
    recovery_entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_operator_escalation_recovery_events.jsonl"
    )
    if not escalation_entries and not recovery_entries:
        return {
            "available": False,
            "recent_escalation_priority_counts": {},
            "recent_resolved_priority_counts": {},
            "recent_unresolved_priority_counts": {},
            "recent_high_priority_escalation_count": 0,
            "recent_high_priority_resolved_count": 0,
            "recent_high_priority_unresolved_count": 0,
            "top_recent_escalation_priority": None,
            "top_recent_resolved_priority": None,
            "top_recent_unresolved_priority": None,
        }

    recent_escalations = escalation_entries[-limit:]
    recent_recoveries = recovery_entries[-limit:]
    escalation_priority_counts: dict[str, int] = {}
    resolved_priority_counts: dict[str, int] = {}
    matched_escalation_indexes: set[int] = set()

    for entry in recent_escalations:
        priority_key = _coerce_optional_text(entry.get("policy_priority"))
        if priority_key is None:
            continue
        escalation_priority_counts[priority_key] = (
            escalation_priority_counts.get(priority_key, 0) + 1
        )

    for recovery_entry in recent_recoveries:
        recovery_at = _coerce_optional_text(recovery_entry.get("generated_at"))
        matched_index = None
        for index in range(len(recent_escalations) - 1, -1, -1):
            if index in matched_escalation_indexes:
                continue
            escalation_at = _coerce_optional_text(
                recent_escalations[index].get("generated_at")
            )
            if (
                escalation_at
                and recovery_at
                and _utc_timestamp_leq(escalation_at, recovery_at)
            ):
                matched_index = index
                break
        if matched_index is None:
            continue
        matched_escalation_indexes.add(matched_index)
        priority_key = _coerce_optional_text(
            recent_escalations[matched_index].get("policy_priority")
        )
        if priority_key is None:
            continue
        resolved_priority_counts[priority_key] = (
            resolved_priority_counts.get(priority_key, 0) + 1
        )

    unresolved_priority_counts: dict[str, int] = {}
    for priority_key, escalation_count in escalation_priority_counts.items():
        unresolved_count = max(
            0, escalation_count - resolved_priority_counts.get(priority_key, 0)
        )
        if unresolved_count:
            unresolved_priority_counts[priority_key] = unresolved_count

    def _top_priority(counts: dict[str, int]) -> str | None:
        return (
            sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
            if counts
            else None
        )

    return {
        "available": True,
        "recent_escalation_priority_counts": escalation_priority_counts,
        "recent_resolved_priority_counts": resolved_priority_counts,
        "recent_unresolved_priority_counts": unresolved_priority_counts,
        "recent_high_priority_escalation_count": int(
            escalation_priority_counts.get("high", 0) or 0
        ),
        "recent_high_priority_resolved_count": int(
            resolved_priority_counts.get("high", 0) or 0
        ),
        "recent_high_priority_unresolved_count": int(
            unresolved_priority_counts.get("high", 0) or 0
        ),
        "top_recent_escalation_priority": _top_priority(escalation_priority_counts),
        "top_recent_resolved_priority": _top_priority(resolved_priority_counts),
        "top_recent_unresolved_priority": _top_priority(unresolved_priority_counts),
    }


__all__ = [
    "_hybrid_collection_operator_escalation_event_stability_summary",
    "_hybrid_collection_operator_escalation_recovery_event_summary",
    "_hybrid_collection_operator_intervention_event_summary",
    "_hybrid_collection_unresolved_escalation_window_summary",
    "_hybrid_collection_escalation_resolution_trend_summary",
    "_hybrid_collection_escalation_priority_mix_trend_summary",
]
