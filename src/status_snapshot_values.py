"""Read cached status snapshots and normalize their optional scalar values."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import SupportsFloat, SupportsIndex, SupportsInt, cast

from src.runtime_snapshot_cache import snapshots


def _load_json_snapshot(path: Path) -> dict[str, object]:
    return cast(dict[str, object], snapshots.read(path))


def _load_jsonl_snapshots(path: Path) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], snapshots.read(path, lines=True))


def _coerce_optional_mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_optional_int(value: object) -> int | None:
    if value in {None, "", "unknown"}:
        return None
    try:
        return int(cast("str | bytes | bytearray | SupportsInt | SupportsIndex", value))
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(value: object) -> float | None:
    if value in {None, "", "unknown"}:
        return None
    try:
        return float(
            cast("str | bytes | bytearray | SupportsFloat | SupportsIndex", value)
        )
    except (TypeError, ValueError):
        return None


def _coerce_optional_bool(value: object) -> bool | None:
    if value in {None, "", "unknown"}:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
        return None
    return bool(value)


def _coerce_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized in {"", "unknown"}:
        return None
    return normalized


def _coerce_optional_iso_datetime(value: object) -> datetime.datetime | None:
    text = _coerce_optional_text(value)
    if text is None:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


__all__ = [
    "_load_json_snapshot",
    "_load_jsonl_snapshots",
    "_coerce_optional_mapping",
    "_coerce_optional_int",
    "_coerce_optional_float",
    "_coerce_optional_bool",
    "_coerce_optional_text",
    "_coerce_optional_iso_datetime",
]
