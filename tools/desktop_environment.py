"""Scoped desktop aliases with lexical path equivalence, never global fallback."""

import os
from collections.abc import Mapping
from pathlib import Path

from src.project_environment import EnvironmentAliasConflict, getenv

CANONICAL_PATH_KEYS = frozenset(
    {
        "CROW_DATA_ROOT_HOST",
        "CROW_COOKIE_SNAPSHOT",
        "CROW_NAS_AUTH_RECOVERY_TOKEN_FILE",
        "CROW_AUTH_BROWSER_PROFILE_DIR",
        "CROW_AUTH_BROWSER_PATH",
        "CROW_SETTINGS_CA_FILE",
        "CROW_ENGINE_OPERATOR_TOKEN_FILE",
        "CROW_API_CA_FILE",
        "CROW_DESKTOP_PYTHON_PATH",
    }
)


def aliases(name: str) -> tuple[str, ...]:
    canonical = "CROW_" + name[6:] if name.startswith("FAPAI_") else name
    return (
        (canonical, "FAPAI_" + canonical[5:])
        if canonical.startswith("CROW_")
        else (name,)
    )


PATH_KEYS = frozenset(name for key in CANONICAL_PATH_KEYS for name in aliases(key))
ALLOWED_KEYS = PATH_KEYS | frozenset(
    name
    for key in (
        "CROW_COLLECTOR_API_BASE",
        "CROW_AUTH_LOCAL_CDP_PORT",
        "CROW_SETTINGS_API_BASE",
    )
    for name in aliases(key)
)


def environment_value(
    name: str, default: str | None = None, *, environment: Mapping[str, str], root: Path
) -> str | None:
    """Keep original values, comparing paths without dereferencing links.

    Only management-root blanks are ignored, matching the management resolver.
    Other explicit empty aliases remain values. Saved paths are already absolute;
    relative process paths retain their original current-directory semantics.
    Windows path case/UNC semantics
    come from pathlib on Windows; separate POSIX spellings remain distinct.
    """
    names = aliases(name)
    if names[0] not in CANONICAL_PATH_KEYS:
        return getenv(name, default, reader=environment.get)
    management_root = names[0] == "CROW_DATA_ROOT_HOST"
    values = [environment[key] for key in names if key in environment]
    if management_root:
        values = [value for value in values if value.strip()]

    def identity(value: str) -> Path | None:
        if management_root:
            value = value.strip()
        if not value:
            return None
        path = Path(value)
        base = root if management_root else Path.cwd()
        return Path(os.path.abspath(path if path.is_absolute() else base / path))

    if len({identity(value) for value in values}) > 1:
        raise EnvironmentAliasConflict(
            "Conflicting environment aliases: " + ", ".join(names)
        )
    return values[0] if values else default
