"""Bounded parsing of Compose selectors; never validate a different target."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


class ComposeEnvironmentError(ValueError):
    pass


@dataclass(frozen=True)
class ComposeInputs:
    root: Path
    env_files: tuple[Path, ...]
    explicit_files: bool
    explicit_env_files: bool
    global_arguments: tuple[str, ...] = ()


VALUE_OPTIONS = frozenset(
    {
        "-f",
        "--file",
        "-p",
        "--project-name",
        "--env-file",
        "--project-directory",
        "--profile",
        "--parallel",
        "--ansi",
        "--progress",
    }
)
FLAG_OPTIONS = frozenset({"--compatibility", "--dry-run", "--all-resources"})


def _option(item: str) -> tuple[str, str | None]:
    if item.startswith(("-f", "-p")) and not item.startswith("--") and len(item) > 2:
        value = item[2:]
        return item[:2], value.removeprefix("=")
    name, equal, value = item.partition("=")
    return name, value if equal else None


def compose_inputs(arguments: Sequence[str], cwd: Path) -> ComposeInputs:
    root: Path | None = None
    files: list[Path] = []
    compose_files: list[Path] = []
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if not item.startswith("-"):
            # Docker accepts some global flags after commands. This adapter does
            # not: doing so could change selectors after validation had stopped.
            for tail in arguments[index + 1 :]:
                name, _ = _option(tail)
                if name in VALUE_OPTIONS or name in FLAG_OPTIONS:
                    raise ComposeEnvironmentError(
                        "Compose global options must precede the command"
                    )
            break
        option, value = _option(item)
        if option in FLAG_OPTIONS and value is None:
            index += 1
            continue
        if option not in VALUE_OPTIONS:
            raise ComposeEnvironmentError("Unsupported Compose global option")
        if value is None:
            index += 1
            if index >= len(arguments):
                raise ComposeEnvironmentError("Missing Compose option value")
            value = arguments[index]
        if not value or (
            value.startswith("-") and not (option == "--parallel" and value == "-1")
        ):
            raise ComposeEnvironmentError("Missing or unsupported Compose option value")
        if option in {"--env-file", "--project-directory", "--file", "-f"}:
            if "://" in value:
                raise ComposeEnvironmentError(
                    "Crow Compose requires local configuration files"
                )
            path = Path(os.path.abspath(cwd / value))
            if option == "--env-file":
                files.append(path)
            elif option == "--project-directory":
                if root is not None:
                    raise ComposeEnvironmentError(
                        "Repeated Compose project directory is ambiguous"
                    )
                root = path
            else:
                compose_files.append(path)
        index += 1
    root = (
        root if root is not None else compose_files[0].parent if compose_files else cwd
    )
    explicit_env_files = bool(files)
    if not files:
        if (root / ".env").is_file():
            files.append(root / ".env")
        if cwd != root and (cwd / ".env").is_file():
            files.append(cwd / ".env")
    return ComposeInputs(
        root,
        tuple(files),
        bool(compose_files),
        explicit_env_files,
        tuple(arguments[:index]),
    )


def reject_indirect_selectors(
    inputs: ComposeInputs, environment: Mapping[str, str]
) -> None:
    if environment.get("COMPOSE_FILE") and not inputs.explicit_files:
        raise ComposeEnvironmentError("Pass Compose files explicitly with -f")
    if environment.get("COMPOSE_ENV_FILES") and not inputs.explicit_env_files:
        raise ComposeEnvironmentError(
            "Pass Compose environment files explicitly with --env-file"
        )
