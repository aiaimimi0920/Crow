"""Collection record discovery and bounded maintenance publication."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from src.archive_json_io import read_records, write_records
from src.collection_job_control import job_checkpoint

from .contracts import Record

if TYPE_CHECKING:
    from src.storage.repository import CollectionRepository


def normalize_data_root(path: Path) -> Path:
    candidate = Path(path)
    return candidate.parent if candidate.name.lower() == "archive" else candidate


def discover_raw_record_files(data_root: Path) -> list[Path]:
    root = normalize_data_root(data_root)
    archived = sorted((root / "archive").rglob("*.json"))
    current = sorted(root.glob("*.json"))
    return list(dict.fromkeys(path for path in (*archived, *current) if path.is_file()))


def load_json_payload(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def iter_recent_rows(
    data_root: Path, window_days: int, repository: CollectionRepository
) -> list[Record]:
    if repository.enabled:
        return [
            dict(
                row,
                __file_path=str(
                    row.get("__file_path")
                    or row.get("json_file")
                    or row.get("source_json_path")
                    or ""
                ),
            )
            for row in repository.iter_recent_flat_items(window_days)
        ]
    dated = []
    for path in discover_raw_record_files(data_root):
        try:
            dated.append((path, datetime.strptime(path.stem, "%Y-%m-%d")))
        except ValueError:
            continue
    latest = max((date for _, date in dated), default=None)
    if latest is None:
        return []
    start = latest - timedelta(days=max(window_days - 1, 0))
    rows: list[Record] = []
    for path, date in dated:
        job_checkpoint()
        if date >= start:
            rows.extend(dict(row, __file_path=str(path)) for row in read_records(path))
    return rows


def apply_record_patch(record: Record, patch: Record) -> None:
    """Update matching canonical fields without deleting unknown stored sections."""
    record.update(patch)
    for name in (
        "source",
        "archive",
        "auction",
        "location",
        "property",
        "legal_context",
        "risk_flags",
        "audit",
    ):
        section = record.get(name)
        if isinstance(section, dict):
            section.update(
                {key: value for key, value in patch.items() if key in section}
            )


def publish_records(
    path: Path,
    rows: list[Record],
    changed: list[Record],
    repository: CollectionRepository,
    event_type: str,
) -> None:
    job_checkpoint()
    write_records(path, rows)
    if repository.enabled:
        repository.upsert_flat_items(
            changed,
            event_type=event_type,
            event_payload_factory=lambda record, _index: {
                "source_file": str(path),
                "item_id": str(record["source"]["item_id"]),
            },
        )
    job_checkpoint()
