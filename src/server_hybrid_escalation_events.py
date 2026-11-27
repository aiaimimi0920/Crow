from __future__ import annotations

from pathlib import Path
from typing import Any

from src.status_snapshot_values import (
    _coerce_optional_text,
    _load_jsonl_snapshots,
)


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
            escalation_kind_counts[escalation_kind] = (
                escalation_kind_counts.get(escalation_kind, 0) + 1
            )
        escalation_source = _coerce_optional_text(
            entry.get("operator_escalation_source")
        )
        if escalation_source:
            escalation_source_counts[escalation_source] = (
                escalation_source_counts.get(escalation_source, 0) + 1
            )
        policy_status = _coerce_optional_text(entry.get("policy_status"))
        if policy_status:
            policy_status_counts[policy_status] = (
                policy_status_counts.get(policy_status, 0) + 1
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
    "_hybrid_collection_operator_escalation_event_summary",
    "_hybrid_collection_operator_escalation_event_trend_summary",
]
