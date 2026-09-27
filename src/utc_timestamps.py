"""UTC timestamp handling shared by collection runtime and read-only summaries."""

from __future__ import annotations

import datetime
import re


def _utc_now() -> datetime.datetime:
    """Return an aware UTC instant while tolerating legacy zero-argument clocks."""
    try:
        value = datetime.datetime.now(datetime.timezone.utc)
    except TypeError:
        value = datetime.datetime.now()
    return (
        value
        if value.tzinfo is not None
        else value.replace(tzinfo=datetime.timezone.utc)
    )


def _as_utc_timestamp(value: datetime.datetime | None) -> datetime.datetime | None:
    """Normalize legacy naive dispatch timestamps as UTC for safe subtraction."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _parse_utc_timestamp(value: object) -> datetime.datetime | None:
    """Parse legacy or ISO timestamps and normalize them to aware UTC."""
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.datetime.fromisoformat(normalized)
    except (AttributeError, TypeError, ValueError):
        try:
            parsed = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except (AttributeError, TypeError, ValueError):
            return None
    return _as_utc_timestamp(parsed)


def _utc_timestamp_leq(left: object, right: object) -> bool:
    """Compare canonical mixed timestamps by UTC while preserving legacy ordering."""
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    left_dt = _parse_utc_timestamp(left_text)
    right_dt = _parse_utc_timestamp(right_text)
    canonical = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$")
    if (
        left_dt is not None
        and right_dt is not None
        and canonical.fullmatch(left_text)
        and canonical.fullmatch(right_text)
    ):
        return left_dt <= right_dt
    return left_text <= right_text
