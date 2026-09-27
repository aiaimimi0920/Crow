"""Atomic cookie snapshot persistence shared by runtime and command-line tools."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import cast


def write_cookie_snapshot(
    cookies: Iterable[Mapping[str, object]], output_path: str | Path
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = json.dumps(list(cookies), ensure_ascii=False, indent=2)
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def load_cookie_snapshot(output_path: str | Path) -> list[dict[str, object]]:
    payload: object = json.loads(Path(output_path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        # Public CLI callers historically receive ValueError for this document.
        raise ValueError("Cookie snapshot must be a JSON list.")  # noqa: TRY004
    # Preserve the existing list-only validation contract for tool callers.
    return cast(list[dict[str, object]], payload)
