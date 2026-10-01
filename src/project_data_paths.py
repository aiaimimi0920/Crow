"""Resolve Crow's management root without creating or moving runtime data."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from src.project_environment import getenv as project_getenv

ROOT_KEYS = ("CROW_DATA_ROOT_HOST", "FAPAI_DATA_ROOT_HOST")
SHELL_FILES = {".gitignore", "README.md"}


def _path(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return Path(os.path.abspath(path if path.is_absolute() else root / path))


def _configured(values: Mapping[str, str], root: Path) -> Path | None:
    paths = [
        _path(values[key].strip(), root)
        for key in ROOT_KEYS
        if values.get(key, "").strip()
    ]
    if len(set(paths)) > 1:
        raise ValueError(
            "Conflicting CROW_DATA_ROOT_HOST and FAPAI_DATA_ROOT_HOST; select one root explicitly"
        )
    return paths[0] if paths else None


def _local_settings(root: Path) -> dict[str, str]:
    path = root / "docker.local.env"
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.fullmatch(
            r"\s*(?:export\s+)?(CROW_DATA_ROOT_HOST|FAPAI_DATA_ROOT_HOST)\s*=\s*(.*)",
            line,
        )
        if not match:
            continue
        key, raw = match.groups()
        value = raw.strip()
        if value.startswith(('"', "'")):
            quoted = re.fullmatch(r"([\"'])(.*?)\1(?:\s+#.*)?", value)
            if not quoted:
                raise ValueError(f"Invalid quoted {key} in docker.local.env")
            value = quoted.group(2)
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
            if '"' in value or "'" in value:
                raise ValueError(f"Invalid unquoted {key} in docker.local.env")
        if "${" in value or "$(" in value or re.search(r"\$[A-Za-z_]", value):
            raise ValueError(
                f"Unexpanded {key} in docker.local.env; use a literal path"
            )
        if key in result and result[key] != value:
            raise ValueError(f"Conflicting duplicate {key} in docker.local.env")
        result[key] = value
    return result


def resolve_project_data_root(
    repo_root: str | Path,
    explicit: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    """CLI > process management-root variables > local env file > existing data.

    FAPAI_DATA_ROOT names a *datas subdirectory*, not this management root.
    A checkout-only README/.gitignore shell is not an existing installation.
    All inspection is read-only. Ambiguity and inspection errors fail closed.
    """
    root = Path(os.path.abspath(repo_root))
    if explicit is not None and str(explicit).strip():
        return _path(explicit, root)
    configured = _configured(os.environ if env is None else env, root)
    if configured is None:
        configured = _configured(_local_settings(root), root)
    if configured is not None:
        return configured
    candidates: list[Path] = []
    names: dict[str, list[Path]] = {}
    for child in root.iterdir():
        name = child.name.casefold()
        if name not in {"crowdata", "fpfdata"}:
            continue
        names.setdefault(name, []).append(child)
        if not child.is_dir():
            raise ValueError(f"Runtime data root is not a readable directory: {child}")
        if any(
            entry.name not in SHELL_FILES or entry.is_symlink() or not entry.is_file()
            for entry in child.iterdir()
        ):
            candidates.append(child)
    if any(len(paths) > 1 for paths in names.values()):
        raise ValueError(
            "Multiple case variants of a runtime data root; select one explicitly"
        )
    if len(candidates) > 1:
        raise ValueError(
            "CrowData and FPFData both contain runtime data; select one explicitly"
        )
    if candidates:
        return candidates[0]
    return names.get("crowdata", [root / "CrowData"])[0]


def resolve_collection_data_dir(
    repo_root: str | Path, explicit: str | Path | None = None
) -> Path:
    """Preserve the legacy collection-subdirectory override's meaning."""
    value = explicit or project_getenv("CROW_DATA_ROOT")
    return (
        Path(value).resolve()
        if value
        else resolve_project_data_root(repo_root) / "datas"
    )
