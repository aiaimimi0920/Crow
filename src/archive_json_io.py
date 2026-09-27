"""Fail closed on unreadable archives and publish JSON or UTF-8 text atomically."""

import json
import os
import tempfile
from pathlib import Path
from typing import cast

from src.runtime_json import load_json_file


def read_records(path: str | Path) -> list[dict[str, object]]:
    try:
        payload = load_json_file(path)
    except FileNotFoundError:
        return []
    if not isinstance(payload, list) or any(
        not isinstance(row, dict) for row in payload
    ):
        raise ValueError("Archive must contain a list of record objects")
    return cast(list[dict[str, object]], payload)


def write_records(path: str | Path, records: object, *, indent: int = 4) -> None:
    write_json(path, records, indent=indent)


def write_json(path: str | Path, value: object, *, indent: int = 4) -> None:
    serialized = json.dumps(value, ensure_ascii=False, indent=indent)
    write_text(path, serialized)


def write_text(path: str | Path, content: str) -> None:
    """Publish UTF-8 evidence without truncating a confirmed archive."""
    target = Path(path)
    # Retain an incomplete/failed temporary snapshot for recovery; never truncate
    # the confirmed archive before writing, flush and fsync all succeed.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix="." + target.name + ".pending-",
        suffix=".tmp",
        dir=target.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = handle.name
    os.replace(temporary, target)
