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


def _hybrid_collection_operator_digest_stability_summary(
    digest_trend_summary: dict[str, Any],
) -> dict[str, Any]:
    digest_trend_summary = _coerce_optional_mapping(digest_trend_summary)
    if _coerce_optional_bool(digest_trend_summary.get("available")) is not True:
        return {
            "available": False,
            "stability_status": "unknown",
            "stability_severity": "info",
            "current_digest_status": None,
            "current_digest_priority": None,
            "current_digest_message": None,
            "previous_digest_status": None,
            "previous_digest_message": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": None,
        }

    current_digest_status = _coerce_optional_text(
        digest_trend_summary.get("current_digest_status")
    )
    current_digest_priority = _coerce_optional_text(
        digest_trend_summary.get("current_digest_priority")
    )
    current_digest_message = _coerce_optional_text(
        digest_trend_summary.get("current_digest_message")
    )
    previous_digest_status = _coerce_optional_text(
        digest_trend_summary.get("previous_distinct_digest_status")
    )
    previous_digest_message = _coerce_optional_text(
        digest_trend_summary.get("previous_distinct_digest_message")
    )
    recent_change_count = (
        _coerce_optional_int(digest_trend_summary.get("recent_change_count")) or 0
    )
    if recent_change_count < 0:
        recent_change_count = 0
    last_change_at = _coerce_optional_text(digest_trend_summary.get("last_change_at"))

    if current_digest_priority is None:
        if current_digest_status == "intervention_required":
            current_digest_priority = "high"
        elif current_digest_status == "attention_required":
            current_digest_priority = "warning"
        elif current_digest_status == "ready":
            current_digest_priority = "info"

    if recent_change_count >= 2:
        stability_status = "digest_flapping"
        stability_severity = "warning"
        operator_readable_explanation = (
            "Operator digest changed multiple times recently."
        )
    elif (
        current_digest_priority in {"warning", "high"}
        and recent_change_count > 0
        and previous_digest_status
        and current_digest_status
    ):
        stability_status = "digest_recently_shifted"
        stability_severity = "high" if current_digest_priority == "high" else "warning"
        operator_readable_explanation = f"Operator digest recently shifted from {previous_digest_status} to {current_digest_status}."
    elif current_digest_priority in {"warning", "high"} and recent_change_count == 0:
        stability_status = "persistent_noninfo_digest"
        stability_severity = "high" if current_digest_priority == "high" else "warning"
        operator_readable_explanation = (
            "Operator digest remains non-info with no recent message changes."
        )
    elif current_digest_priority == "info" and recent_change_count == 0:
        stability_status = "stable_digest"
        stability_severity = "info"
        operator_readable_explanation = (
            "Operator digest remains stable with no recent message changes."
        )
    else:
        stability_status = "digest_transitioning"
        stability_severity = "warning"
        operator_readable_explanation = (
            f"Operator digest is transitioning and currently in {current_digest_status}."
            if current_digest_status is not None
            else "Operator digest is transitioning."
        )

    return {
        "available": True,
        "stability_status": stability_status,
        "stability_severity": stability_severity,
        "current_digest_status": current_digest_status,
        "current_digest_priority": current_digest_priority,
        "current_digest_message": current_digest_message,
        "previous_digest_status": previous_digest_status,
        "previous_digest_message": previous_digest_message,
        "recent_change_count": recent_change_count,
        "last_change_at": last_change_at,
        "operator_readable_explanation": operator_readable_explanation,
    }


def _hybrid_collection_operator_intervention_trend_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_collection_runtime_history.jsonl"
    )
    if not entries:
        return {
            "available": False,
            "recent_status_entry_count": 0,
            "recent_intervention_status_counts": {},
            "recent_distinct_intervention_status_count": 0,
            "recent_change_count": 0,
            "top_intervention_status": None,
            "current_intervention_status": None,
            "current_intervention_priority": None,
            "current_intervention_reason": None,
            "previous_distinct_intervention_status": None,
            "last_change_at": None,
        }

    recent_entries = entries[-limit:]
    status_entries: list[tuple[str | None, str, str | None, str | None]] = []
    for entry in recent_entries:
        generated_at = _coerce_optional_text(entry.get("generated_at"))
        status = entry.get("intervention_status")
        if isinstance(status, str) and status.strip() not in {"", "unknown"}:
            status_entries.append(
                (
                    generated_at,
                    status.strip(),
                    _coerce_optional_text(entry.get("intervention_priority")),
                    _coerce_optional_text(entry.get("intervention_reason")),
                )
            )

    if not status_entries:
        return {
            "available": False,
            "recent_status_entry_count": 0,
            "recent_intervention_status_counts": {},
            "recent_distinct_intervention_status_count": 0,
            "recent_change_count": 0,
            "top_intervention_status": None,
            "current_intervention_status": None,
            "current_intervention_priority": None,
            "current_intervention_reason": None,
            "previous_distinct_intervention_status": None,
            "last_change_at": None,
        }

    status_counts: dict[str, int] = {}
    recent_change_count = 0
    last_change_at = None
    previous_status = None
    for generated_at, status, _priority, _reason in status_entries:
        status_counts[status] = status_counts.get(status, 0) + 1
        if previous_status is not None and status != previous_status:
            recent_change_count += 1
            last_change_at = generated_at
        previous_status = status

    (
        current_generated_at,
        current_intervention_status,
        current_intervention_priority,
        current_intervention_reason,
    ) = status_entries[-1]
    previous_distinct_intervention_status = None
    for _generated_at, status, _priority, _reason in reversed(status_entries[:-1]):
        if status != current_intervention_status:
            previous_distinct_intervention_status = status
            break

    top_intervention_status = sorted(
        status_counts.items(), key=lambda item: (-item[1], item[0])
    )[0][0]
    return {
        "available": True,
        "recent_status_entry_count": len(status_entries),
        "recent_intervention_status_counts": status_counts,
        "recent_distinct_intervention_status_count": len(status_counts),
        "recent_change_count": recent_change_count,
        "top_intervention_status": top_intervention_status,
        "current_intervention_status": current_intervention_status,
        "current_intervention_priority": current_intervention_priority,
        "current_intervention_reason": current_intervention_reason,
        "previous_distinct_intervention_status": previous_distinct_intervention_status,
        "last_change_at": last_change_at,
    }


def _hybrid_collection_mode_switch_event_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_mode_switch_events.jsonl"
    )
    if not entries:
        return {
            "available": False,
            "entry_count": 0,
            "recent_switch_count": 0,
            "recent_target_mode_counts": {},
            "recent_guidance_status_counts": {},
            "top_target_mode": None,
            "top_guidance_reason": None,
            "last_switch_at": None,
            "last_switch_session_id": None,
        }

    recent_entries = entries[-limit:]
    target_mode_counts: dict[str, int] = {}
    guidance_status_counts: dict[str, int] = {}
    guidance_reason_counts: dict[str, int] = {}
    for entry in recent_entries:
        target_mode = _coerce_optional_text(entry.get("effective_mode"))
        if target_mode:
            target_key = target_mode
            target_mode_counts[target_key] = target_mode_counts.get(target_key, 0) + 1
        guidance_status = _coerce_optional_text(entry.get("guidance_status"))
        if guidance_status:
            status_key = guidance_status
            guidance_status_counts[status_key] = (
                guidance_status_counts.get(status_key, 0) + 1
            )
        guidance_reason = _coerce_optional_text(entry.get("top_guidance_reason"))
        if guidance_reason:
            reason_key = guidance_reason
            guidance_reason_counts[reason_key] = (
                guidance_reason_counts.get(reason_key, 0) + 1
            )

    top_target_mode = (
        sorted(target_mode_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if target_mode_counts
        else None
    )
    top_guidance_reason = (
        sorted(guidance_reason_counts.items(), key=lambda item: (-item[1], item[0]))[0][
            0
        ]
        if guidance_reason_counts
        else None
    )
    last_entry = recent_entries[-1]
    return {
        "available": True,
        "entry_count": len(entries),
        "recent_switch_count": len(recent_entries),
        "recent_target_mode_counts": target_mode_counts,
        "recent_guidance_status_counts": guidance_status_counts,
        "top_target_mode": top_target_mode,
        "top_guidance_reason": top_guidance_reason,
        "last_switch_at": _coerce_optional_text(last_entry.get("generated_at")),
        "last_switch_session_id": _coerce_optional_text(last_entry.get("session_id")),
    }


def _hybrid_collection_recovery_policy_event_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_recovery_policy_events.jsonl"
    )
    if not entries:
        return {
            "available": False,
            "entry_count": 0,
            "recent_transition_count": 0,
            "recent_transition_kind_counts": {},
            "recent_to_policy_status_counts": {},
            "top_transition_kind": None,
            "top_to_policy_status": None,
            "last_transition_at": None,
            "last_transition_session_id": None,
            "last_transition_kind": None,
            "last_to_policy_status": None,
        }

    recent_entries = entries[-limit:]
    transition_kind_counts: dict[str, int] = {}
    to_policy_status_counts: dict[str, int] = {}
    for entry in recent_entries:
        transition_kind = _coerce_optional_text(entry.get("transition_kind"))
        if transition_kind:
            transition_key = transition_kind
            transition_kind_counts[transition_key] = (
                transition_kind_counts.get(transition_key, 0) + 1
            )
        to_policy_status = _coerce_optional_text(entry.get("to_policy_status"))
        if to_policy_status:
            status_key = to_policy_status
            to_policy_status_counts[status_key] = (
                to_policy_status_counts.get(status_key, 0) + 1
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
        "recent_transition_count": len(recent_entries),
        "recent_transition_kind_counts": transition_kind_counts,
        "recent_to_policy_status_counts": to_policy_status_counts,
        "top_transition_kind": top_transition_kind,
        "top_to_policy_status": top_to_policy_status,
        "last_transition_at": _coerce_optional_text(last_entry.get("generated_at")),
        "last_transition_session_id": _coerce_optional_text(
            last_entry.get("session_id")
        ),
        "last_transition_kind": _coerce_optional_text(
            last_entry.get("transition_kind")
        ),
        "last_to_policy_status": _coerce_optional_text(
            last_entry.get("to_policy_status")
        ),
    }


def _hybrid_collection_operator_escalation_event_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_operator_escalation_events.jsonl"
    )
    if not entries:
        return {
            "available": False,
            "entry_count": 0,
            "recent_event_count": 0,
            "recent_escalation_kind_counts": {},
            "recent_operator_escalation_source_counts": {},
            "recent_policy_status_counts": {},
            "top_escalation_kind": None,
            "top_operator_escalation_source": None,
            "top_policy_status": None,
            "last_event_at": None,
            "last_event_session_id": None,
            "last_operator_escalation_source": None,
            "last_operator_escalation_audit_message": None,
        }

    recent_entries = entries[-limit:]
    escalation_kind_counts: dict[str, int] = {}
    escalation_source_counts: dict[str, int] = {}
    policy_status_counts: dict[str, int] = {}
    for entry in recent_entries:
        escalation_kind = _coerce_optional_text(entry.get("escalation_kind"))
        if escalation_kind:
            kind_key = escalation_kind
            escalation_kind_counts[kind_key] = (
                escalation_kind_counts.get(kind_key, 0) + 1
            )
        escalation_source = _coerce_optional_text(
            entry.get("operator_escalation_source")
        )
        if escalation_source:
            source_key = escalation_source
            escalation_source_counts[source_key] = (
                escalation_source_counts.get(source_key, 0) + 1
            )
        policy_status = _coerce_optional_text(entry.get("policy_status"))
        if policy_status:
            status_key = policy_status
            policy_status_counts[status_key] = (
                policy_status_counts.get(status_key, 0) + 1
            )

    top_escalation_kind = (
        sorted(escalation_kind_counts.items(), key=lambda item: (-item[1], item[0]))[0][
            0
        ]
        if escalation_kind_counts
        else None
    )
    top_operator_escalation_source = (
        sorted(escalation_source_counts.items(), key=lambda item: (-item[1], item[0]))[
            0
        ][0]
        if escalation_source_counts
        else None
    )
    top_policy_status = (
        sorted(policy_status_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if policy_status_counts
        else None
    )
    last_entry = recent_entries[-1]
    return {
        "available": True,
        "entry_count": len(entries),
        "recent_event_count": len(recent_entries),
        "recent_escalation_kind_counts": escalation_kind_counts,
        "recent_operator_escalation_source_counts": escalation_source_counts,
        "recent_policy_status_counts": policy_status_counts,
        "top_escalation_kind": top_escalation_kind,
        "top_operator_escalation_source": top_operator_escalation_source,
        "top_policy_status": top_policy_status,
        "last_event_at": _coerce_optional_text(last_entry.get("generated_at")),
        "last_event_session_id": _coerce_optional_text(last_entry.get("session_id")),
        "last_operator_escalation_source": _coerce_optional_text(
            last_entry.get("operator_escalation_source")
        ),
        "last_operator_escalation_audit_message": _coerce_optional_text(
            last_entry.get("operator_escalation_audit_message")
        ),
    }


def _hybrid_collection_operator_escalation_event_trend_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_operator_escalation_events.jsonl"
    )
    if not entries:
        return {
            "available": False,
            "recent_event_entry_count": 0,
            "recent_operator_escalation_source_counts": {},
            "recent_distinct_operator_escalation_source_count": 0,
            "recent_source_change_count": 0,
            "top_operator_escalation_source": None,
            "current_operator_escalation_source": None,
            "current_escalation_kind": None,
            "current_operator_escalation_audit_message": None,
            "previous_distinct_operator_escalation_source": None,
            "last_source_change_at": None,
        }

    recent_entries = entries[-limit:]
    source_entries: list[tuple[str | None, str, str | None, str | None]] = []
    for entry in recent_entries:
        generated_at = _coerce_optional_text(entry.get("generated_at"))
        source = entry.get("operator_escalation_source")
        if isinstance(source, str) and source.strip() not in {"", "unknown"}:
            source_entries.append(
                (
                    generated_at,
                    source.strip(),
                    _coerce_optional_text(entry.get("escalation_kind")),
                    _coerce_optional_text(
                        entry.get("operator_escalation_audit_message")
                    ),
                )
            )

    if not source_entries:
        return {
            "available": False,
            "recent_event_entry_count": 0,
            "recent_operator_escalation_source_counts": {},
            "recent_distinct_operator_escalation_source_count": 0,
            "recent_source_change_count": 0,
            "top_operator_escalation_source": None,
            "current_operator_escalation_source": None,
            "current_escalation_kind": None,
            "current_operator_escalation_audit_message": None,
            "previous_distinct_operator_escalation_source": None,
            "last_source_change_at": None,
        }

    source_counts: dict[str, int] = {}
    recent_source_change_count = 0
    last_source_change_at = None
    previous_source = None
    for generated_at, source, _kind, _audit in source_entries:
        source_counts[source] = source_counts.get(source, 0) + 1
        if previous_source is not None and source != previous_source:
            recent_source_change_count += 1
            last_source_change_at = generated_at
        previous_source = source

    _current_generated_at, current_source, current_kind, current_audit = source_entries[
        -1
    ]
    previous_distinct_source = None
    for _generated_at, source, _kind, _audit in reversed(source_entries[:-1]):
        if source != current_source:
            previous_distinct_source = source
            break

    top_source = sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))[0][
        0
    ]
    return {
        "available": True,
        "recent_event_entry_count": len(source_entries),
        "recent_operator_escalation_source_counts": source_counts,
        "recent_distinct_operator_escalation_source_count": len(source_counts),
        "recent_source_change_count": recent_source_change_count,
        "top_operator_escalation_source": top_source,
        "current_operator_escalation_source": current_source,
        "current_escalation_kind": current_kind,
        "current_operator_escalation_audit_message": current_audit,
        "previous_distinct_operator_escalation_source": previous_distinct_source,
        "last_source_change_at": last_source_change_at,
    }


__all__ = [
    "_hybrid_collection_operator_digest_stability_summary",
    "_hybrid_collection_operator_intervention_trend_summary",
    "_hybrid_collection_mode_switch_event_summary",
    "_hybrid_collection_recovery_policy_event_summary",
    "_hybrid_collection_operator_escalation_event_summary",
    "_hybrid_collection_operator_escalation_event_trend_summary",
]
