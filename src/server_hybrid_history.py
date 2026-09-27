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


def _hybrid_collection_runtime_history_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_collection_runtime_history.jsonl"
    )
    if not entries:
        return {
            "available": False,
            "entry_count": 0,
            "recent_runs": 0,
            "recent_decision_counts": {},
            "recent_reason_counts": {},
            "recent_browserless_success_count": 0,
            "recent_browser_fallback_required_count": 0,
            "recent_browser_worker_dispatched_count": 0,
            "recent_browserless_success_rate": 0.0,
            "recent_top_fallback_reason": None,
            "recent_top_termination_reason": None,
            "last_generated_at": None,
            "last_session_id": None,
        }

    recent_entries = entries[-limit:]
    decision_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    termination_counts: dict[str, int] = {}
    for entry in recent_entries:
        for key, value in _coerce_optional_mapping(
            entry.get("decision_counts")
        ).items():
            normalized_key = _coerce_optional_text(key)
            if normalized_key is None:
                continue
            parsed_value = _coerce_optional_int(value)
            if parsed_value is None or parsed_value < 0:
                continue
            decision_counts[normalized_key] = (
                int(decision_counts.get(normalized_key, 0) or 0) + parsed_value
            )
        for key, value in _coerce_optional_mapping(entry.get("reason_counts")).items():
            normalized_key = _coerce_optional_text(key)
            if normalized_key is None:
                continue
            parsed_value = _coerce_optional_int(value)
            if parsed_value is None or parsed_value <= 0:
                continue
            reason_counts[normalized_key] = (
                int(reason_counts.get(normalized_key, 0) or 0) + parsed_value
            )
        normalized_reason = _coerce_optional_text(entry.get("termination_reason"))
        if normalized_reason is not None:
            termination_counts[normalized_reason] = (
                int(termination_counts.get(normalized_reason, 0) or 0) + 1
            )

    browserless_success_count = int(decision_counts.get("browserless_success", 0) or 0)
    browser_fallback_required_count = int(
        decision_counts.get("browser_fallback_required", 0) or 0
    )
    browser_worker_dispatched_count = int(
        decision_counts.get("browser_worker_dispatched", 0) or 0
    )
    attempts = browserless_success_count + browser_fallback_required_count
    top_fallback_reason = (
        sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if reason_counts
        else None
    )
    top_termination_reason = (
        sorted(termination_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if termination_counts
        else None
    )
    last_entry = recent_entries[-1]
    return {
        "available": True,
        "entry_count": len(entries),
        "recent_runs": len(recent_entries),
        "recent_decision_counts": decision_counts,
        "recent_reason_counts": reason_counts,
        "recent_browserless_success_count": browserless_success_count,
        "recent_browser_fallback_required_count": browser_fallback_required_count,
        "recent_browser_worker_dispatched_count": browser_worker_dispatched_count,
        "recent_browserless_success_rate": (browserless_success_count / attempts)
        if attempts > 0
        else 0.0,
        "recent_top_fallback_reason": top_fallback_reason,
        "recent_top_termination_reason": top_termination_reason,
        "last_generated_at": _coerce_optional_text(last_entry.get("generated_at")),
        "last_session_id": _coerce_optional_text(last_entry.get("session_id")),
    }


def _hybrid_collection_action_hint_trend_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_collection_runtime_history.jsonl"
    )
    if not entries:
        return {
            "available": False,
            "recent_hint_entry_count": 0,
            "recent_action_hint_counts": {},
            "recent_distinct_action_hint_count": 0,
            "recent_change_count": 0,
            "top_action_hint": None,
            "current_action_hint": None,
            "previous_distinct_action_hint": None,
            "last_change_at": None,
        }

    recent_entries = entries[-limit:]
    hint_entries: list[tuple[str | None, str]] = []
    for entry in recent_entries:
        generated_at = _coerce_optional_text(entry.get("generated_at"))
        hint = entry.get("operator_action_hint")
        if isinstance(hint, str) and hint.strip() not in {"", "unknown"}:
            hint_entries.append((generated_at, hint.strip()))

    if not hint_entries:
        return {
            "available": False,
            "recent_hint_entry_count": 0,
            "recent_action_hint_counts": {},
            "recent_distinct_action_hint_count": 0,
            "recent_change_count": 0,
            "top_action_hint": None,
            "current_action_hint": None,
            "previous_distinct_action_hint": None,
            "last_change_at": None,
        }

    action_hint_counts: dict[str, int] = {}
    recent_change_count = 0
    last_change_at = None
    previous_hint = None
    for generated_at, hint in hint_entries:
        action_hint_counts[hint] = action_hint_counts.get(hint, 0) + 1
        if previous_hint is not None and hint != previous_hint:
            recent_change_count += 1
            last_change_at = generated_at
        previous_hint = hint

    current_action_hint = hint_entries[-1][1]
    previous_distinct_action_hint = None
    for _, hint in reversed(hint_entries[:-1]):
        if hint != current_action_hint:
            previous_distinct_action_hint = hint
            break

    top_action_hint = sorted(
        action_hint_counts.items(), key=lambda item: (-item[1], item[0])
    )[0][0]
    return {
        "available": True,
        "recent_hint_entry_count": len(hint_entries),
        "recent_action_hint_counts": action_hint_counts,
        "recent_distinct_action_hint_count": len(action_hint_counts),
        "recent_change_count": recent_change_count,
        "top_action_hint": top_action_hint,
        "current_action_hint": current_action_hint,
        "previous_distinct_action_hint": previous_distinct_action_hint,
        "last_change_at": last_change_at,
    }


def _hybrid_collection_operator_final_guidance_trend_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_collection_runtime_history.jsonl"
    )
    if not entries:
        return {
            "available": False,
            "recent_guidance_entry_count": 0,
            "recent_guidance_message_counts": {},
            "recent_distinct_guidance_message_count": 0,
            "recent_change_count": 0,
            "top_guidance_message": None,
            "current_guidance_label": None,
            "current_guidance_priority": None,
            "current_guidance_message": None,
            "previous_distinct_guidance_label": None,
            "previous_distinct_guidance_message": None,
            "last_change_at": None,
        }

    recent_entries = entries[-limit:]
    guidance_entries: list[tuple[str | None, str, str | None, str | None]] = []
    for entry in recent_entries:
        generated_at = _coerce_optional_text(entry.get("generated_at"))
        guidance_message = entry.get("operator_final_guidance_message")
        if isinstance(guidance_message, str) and guidance_message.strip() not in {
            "",
            "unknown",
        }:
            guidance_entries.append(
                (
                    generated_at,
                    guidance_message.strip(),
                    _coerce_optional_text(entry.get("operator_final_guidance_label")),
                    _coerce_optional_text(
                        entry.get("operator_final_guidance_priority")
                    ),
                )
            )

    if not guidance_entries:
        return {
            "available": False,
            "recent_guidance_entry_count": 0,
            "recent_guidance_message_counts": {},
            "recent_distinct_guidance_message_count": 0,
            "recent_change_count": 0,
            "top_guidance_message": None,
            "current_guidance_label": None,
            "current_guidance_priority": None,
            "current_guidance_message": None,
            "previous_distinct_guidance_label": None,
            "previous_distinct_guidance_message": None,
            "last_change_at": None,
        }

    guidance_message_counts: dict[str, int] = {}
    recent_change_count = 0
    last_change_at = None
    previous_message = None
    for generated_at, guidance_message, _label, _priority in guidance_entries:
        guidance_message_counts[guidance_message] = (
            guidance_message_counts.get(guidance_message, 0) + 1
        )
        if previous_message is not None and guidance_message != previous_message:
            recent_change_count += 1
            last_change_at = generated_at
        previous_message = guidance_message

    (
        current_generated_at,
        current_guidance_message,
        current_guidance_label,
        current_guidance_priority,
    ) = guidance_entries[-1]
    previous_distinct_guidance_label = None
    previous_distinct_guidance_message = None
    for _generated_at, guidance_message, label, _priority in reversed(
        guidance_entries[:-1]
    ):
        if guidance_message != current_guidance_message:
            previous_distinct_guidance_label = label
            previous_distinct_guidance_message = guidance_message
            break

    top_guidance_message = sorted(
        guidance_message_counts.items(), key=lambda item: (-item[1], item[0])
    )[0][0]
    return {
        "available": True,
        "recent_guidance_entry_count": len(guidance_entries),
        "recent_guidance_message_counts": guidance_message_counts,
        "recent_distinct_guidance_message_count": len(guidance_message_counts),
        "recent_change_count": recent_change_count,
        "top_guidance_message": top_guidance_message,
        "current_guidance_label": current_guidance_label,
        "current_guidance_priority": current_guidance_priority,
        "current_guidance_message": current_guidance_message,
        "previous_distinct_guidance_label": previous_distinct_guidance_label,
        "previous_distinct_guidance_message": previous_distinct_guidance_message,
        "last_change_at": last_change_at,
    }


def _hybrid_collection_operator_final_guidance_stability_summary(
    final_guidance_trend_summary: dict[str, Any],
) -> dict[str, Any]:
    final_guidance_trend_summary = _coerce_optional_mapping(
        final_guidance_trend_summary
    )
    if _coerce_optional_bool(final_guidance_trend_summary.get("available")) is not True:
        return {
            "available": False,
            "stability_status": "unknown",
            "stability_severity": "info",
            "current_guidance_label": None,
            "current_guidance_priority": None,
            "current_guidance_message": None,
            "previous_guidance_message": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": None,
        }

    current_guidance_label = _coerce_optional_text(
        final_guidance_trend_summary.get("current_guidance_label")
    )
    current_guidance_priority = _coerce_optional_text(
        final_guidance_trend_summary.get("current_guidance_priority")
    )
    current_guidance_message = _coerce_optional_text(
        final_guidance_trend_summary.get("current_guidance_message")
    )
    previous_guidance_label = _coerce_optional_text(
        final_guidance_trend_summary.get("previous_distinct_guidance_label")
    )
    previous_guidance_message = _coerce_optional_text(
        final_guidance_trend_summary.get("previous_distinct_guidance_message")
    )
    recent_change_count = (
        _coerce_optional_int(final_guidance_trend_summary.get("recent_change_count"))
        or 0
    )
    if recent_change_count < 0:
        recent_change_count = 0
    last_change_at = _coerce_optional_text(
        final_guidance_trend_summary.get("last_change_at")
    )

    if current_guidance_priority is None:
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

    if recent_change_count >= 2:
        stability_status = "guidance_flapping"
        stability_severity = "warning"
        operator_readable_explanation = (
            "Final guidance changed multiple times recently."
        )
    elif (
        current_guidance_priority in {"warning", "high"}
        and recent_change_count > 0
        and previous_guidance_label
        and current_guidance_label
    ):
        stability_status = "guidance_recently_shifted"
        stability_severity = (
            "high" if current_guidance_priority == "high" else "warning"
        )
        operator_readable_explanation = f"Final guidance recently shifted from {previous_guidance_label} to {current_guidance_label}."
    elif current_guidance_priority in {"warning", "high"} and recent_change_count == 0:
        stability_status = "persistent_noninfo_guidance"
        stability_severity = (
            "high" if current_guidance_priority == "high" else "warning"
        )
        operator_readable_explanation = (
            "Final guidance remains non-info with no recent message changes."
        )
    elif current_guidance_priority == "info" and recent_change_count == 0:
        stability_status = "stable_guidance"
        stability_severity = "info"
        operator_readable_explanation = (
            "Final guidance remains stable with no recent message changes."
        )
    else:
        stability_status = "guidance_transitioning"
        stability_severity = "warning"
        operator_readable_explanation = (
            f"Final guidance is transitioning and currently in {current_guidance_label}."
            if current_guidance_label is not None
            else "Final guidance is transitioning."
        )

    return {
        "available": True,
        "stability_status": stability_status,
        "stability_severity": stability_severity,
        "current_guidance_label": current_guidance_label,
        "current_guidance_priority": current_guidance_priority,
        "current_guidance_message": current_guidance_message,
        "previous_guidance_message": previous_guidance_message,
        "recent_change_count": recent_change_count,
        "last_change_at": last_change_at,
        "operator_readable_explanation": operator_readable_explanation,
    }


def _hybrid_collection_operator_digest_trend_summary(
    data_root: Path, *, limit: int = 20
) -> dict[str, Any]:
    entries = _load_jsonl_snapshots(
        data_root / "avm" / "hybrid_seed_collection_runtime_history.jsonl"
    )
    if not entries:
        return {
            "available": False,
            "recent_digest_entry_count": 0,
            "recent_digest_message_counts": {},
            "recent_distinct_digest_message_count": 0,
            "recent_change_count": 0,
            "top_digest_message": None,
            "current_digest_status": None,
            "current_digest_priority": None,
            "current_digest_message": None,
            "previous_distinct_digest_status": None,
            "previous_distinct_digest_message": None,
            "last_change_at": None,
        }

    recent_entries = entries[-limit:]
    digest_entries: list[tuple[str | None, str, str | None, str | None]] = []
    for entry in recent_entries:
        generated_at = _coerce_optional_text(entry.get("generated_at"))
        digest_message = entry.get("operator_digest_message")
        if isinstance(digest_message, str) and digest_message.strip() not in {
            "",
            "unknown",
        }:
            digest_entries.append(
                (
                    generated_at,
                    digest_message.strip(),
                    _coerce_optional_text(entry.get("operator_digest_status")),
                    _coerce_optional_text(entry.get("operator_digest_priority")),
                )
            )

    if not digest_entries:
        return {
            "available": False,
            "recent_digest_entry_count": 0,
            "recent_digest_message_counts": {},
            "recent_distinct_digest_message_count": 0,
            "recent_change_count": 0,
            "top_digest_message": None,
            "current_digest_status": None,
            "current_digest_priority": None,
            "current_digest_message": None,
            "previous_distinct_digest_status": None,
            "previous_distinct_digest_message": None,
            "last_change_at": None,
        }

    digest_message_counts: dict[str, int] = {}
    recent_change_count = 0
    last_change_at = None
    previous_message = None
    for generated_at, digest_message, _status, _priority in digest_entries:
        digest_message_counts[digest_message] = (
            digest_message_counts.get(digest_message, 0) + 1
        )
        if previous_message is not None and digest_message != previous_message:
            recent_change_count += 1
            last_change_at = generated_at
        previous_message = digest_message

    (
        _current_generated_at,
        current_digest_message,
        current_digest_status,
        current_digest_priority,
    ) = digest_entries[-1]
    previous_distinct_digest_status = None
    previous_distinct_digest_message = None
    for _generated_at, digest_message, status, _priority in reversed(
        digest_entries[:-1]
    ):
        if digest_message != current_digest_message:
            previous_distinct_digest_status = status
            previous_distinct_digest_message = digest_message
            break

    top_digest_message = sorted(
        digest_message_counts.items(), key=lambda item: (-item[1], item[0])
    )[0][0]
    return {
        "available": True,
        "recent_digest_entry_count": len(digest_entries),
        "recent_digest_message_counts": digest_message_counts,
        "recent_distinct_digest_message_count": len(digest_message_counts),
        "recent_change_count": recent_change_count,
        "top_digest_message": top_digest_message,
        "current_digest_status": current_digest_status,
        "current_digest_priority": current_digest_priority,
        "current_digest_message": current_digest_message,
        "previous_distinct_digest_status": previous_distinct_digest_status,
        "previous_distinct_digest_message": previous_distinct_digest_message,
        "last_change_at": last_change_at,
    }


__all__ = [
    "_hybrid_collection_runtime_history_summary",
    "_hybrid_collection_action_hint_trend_summary",
    "_hybrid_collection_operator_final_guidance_trend_summary",
    "_hybrid_collection_operator_final_guidance_stability_summary",
    "_hybrid_collection_operator_digest_trend_summary",
]
