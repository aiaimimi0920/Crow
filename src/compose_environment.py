"""Prepare legacy Compose inputs from scoped Crow aliases without touching data."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from src.project_environment import EnvironmentAliasConflict

HOST_PATH_KEYS = frozenset(
    {
        "CROW_DATA_ROOT_HOST",
        "CROW_SHARED_DATA_ROOT_HOST",
        "CROW_NAS_DATA_ROOT",
        "CROW_DATA_ROOT",
        "CROW_LEGACY_ARTIFACT_OUTPUT_ROOT",
        "CROW_RUNTIME_ENV_FILE",
        "CROW_NAS_ENV_FILE",
    }
)


def alias_names(key: str) -> tuple[str, str]:
    canonical = "CROW_" + key[6:] if key.startswith("FAPAI_") else key
    return canonical, "FAPAI_" + canonical[5:]


def _path_identity(value: str, root: Path, names: tuple[str, str]) -> Path | None:
    if value == "":
        return None
    if os.name == "nt" and re.match(r"^[A-Za-z]:(?![\\/])", value):
        raise EnvironmentAliasConflict(
            "Drive-relative environment aliases: " + ", ".join(names)
        )
    path = Path(value)
    return Path(os.path.abspath(path if path.is_absolute() else root / path))


def prepare_environment(
    root: Path,
    *,
    file_values: Mapping[str, str],
    process: Mapping[str, str],
    explicit: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Explicit > process > env-file, with each alias pair treated as one input.

    Blank management-root paths fall through like the dedicated selector. Other
    empty process values stay explicit so Compose retains its own :-/:? rules.
    Path comparisons are lexical; this never creates, resolves links or moves data.
    """
    overrides = {} if explicit is None else explicit
    result = {**file_values, **process, **overrides}
    names = {alias_names(key) for key in result if key.startswith(("CROW_", "FAPAI_"))}
    for pair in names:
        is_path = pair[0] in HOST_PATH_KEYS
        selected: list[str] = []
        for source in (overrides, process, file_values):
            selected = [source[key] for key in pair if key in source]
            if any(not isinstance(value, str) for value in selected):
                raise EnvironmentAliasConflict(
                    "Invalid environment aliases: " + ", ".join(pair)
                )
            if pair[0] == "CROW_DATA_ROOT_HOST":
                selected = [value.strip() for value in selected if value.strip()]
            if selected:
                break
        identities = [
            _path_identity(value, root, pair) if is_path else value
            for value in selected
        ]
        if len(set(identities)) > 1:
            raise EnvironmentAliasConflict(
                "Conflicting environment aliases: " + ", ".join(pair)
            )
        for key in pair:
            if selected:
                result[key] = selected[0]
            else:
                result.pop(key, None)
    return result
