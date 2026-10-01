"""Aggregate-only console summaries; full maintenance results stay in reports."""

from __future__ import annotations


def _count(value) -> int | None:
    # Reject numeric-looking strings and custom values rather than echoing them.
    if type(value) is int and 0 <= value <= 1_000_000_000:
        return value
    return None


def coordinate_summary(report: dict) -> dict:
    return {
        "report_written": True,
        "window_days": _count(report.get("window_days")),
        "dry_run": report.get("dry_run") is True,
        "candidate_count": _count(report.get("candidate_count")),
        "updated_count": _count(report.get("updated_count")),
    }


def maintenance_summary(report: dict) -> dict:
    summary = {
        "report_written": True,
        "window_days": _count(report.get("window_days")),
        "dry_run": report.get("dry_run") is True,
    }
    for key in ("executed_actions", "productive_actions"):
        value = report.get(key)
        summary[f"{key}_count"] = len(value) if isinstance(value, list) else None
    return summary
