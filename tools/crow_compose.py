"""Validate Crow/legacy environment aliases before invoking local Docker Compose."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.compose_environment import prepare_environment
from src.project_environment import EnvironmentAliasConflict
from tools.compose_arguments import (
    ComposeEnvironmentError,
    compose_inputs,
    reject_indirect_selectors,
)


def inspect_file_environment(
    root: Path,
    files: Sequence[Path],
    process: Mapping[str, str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    interpolation: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Use Compose's parser on an inert model; capture all values and diagnostics."""
    high = prepare_environment(root, file_values={}, process=process)
    service: dict[str, object] = {"image": "scratch"}
    if files:
        service["env_file"] = [str(path) for path in files]
    service["environment"] = {
        key: value.replace("$", "$$")
        for key, value in high.items()
        if key.startswith(("CROW_", "FAPAI_"))
    }
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(root),
        "-p",
        "crow-env-inspection",
    ]
    for path in files:
        command.extend(["--env-file", str(path)])
    command.extend(["-f", "-", "config", "--format", "json", "--no-path-resolution"])
    try:
        completed = runner(
            command,
            input=json.dumps({"services": {"env-inspection": service}}),
            env={**(interpolation or {}), **high},
            cwd=root,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if completed.returncode:
            raise ComposeEnvironmentError("Compose environment inspection failed")
        values = json.loads(completed.stdout)["services"]["env-inspection"].get(
            "environment", {}
        )
        if not isinstance(values, dict) or any(
            not isinstance(k, str) or (v is not None and not isinstance(v, str))
            for k, v in values.items()
        ):
            raise ComposeEnvironmentError(
                "Compose environment inspection returned invalid values"
            )
        # Compose config escapes dollars for safe reuse as Compose input.
        return {
            key: value.replace("$$", "$")
            for key, value in values.items()
            if value is not None
        }
    except (
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ):
        raise ComposeEnvironmentError(
            "Compose environment inspection unavailable"
        ) from None


def resolve_environment(
    root: Path,
    files: Sequence[Path],
    process: Mapping[str, str],
    explicit: Mapping[str, str],
    *,
    reader: Callable[..., dict[str, str]] = inspect_file_environment,
) -> dict[str, str]:
    high = prepare_environment(root, file_values={}, process=process, explicit=explicit)
    values = reader(root, files, high)
    defined = set(values)
    # Only supply absent alias names for interpolation. Never feed a file's own
    # definitions back into themselves (e.g. KEY=${KEY}suffix).
    for _ in range(8):
        prepared = prepare_environment(
            root, file_values=values, process=process, explicit=explicit
        )
        bridge = {
            key: value
            for key, value in prepared.items()
            if key.startswith(("CROW_", "FAPAI_")) and key not in defined
        }
        if not bridge:
            return prepared
        updated = reader(root, files, high, interpolation=bridge)
        if updated == values:
            return prepared
        values = updated
    raise ComposeEnvironmentError("Cyclic environment alias interpolation")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--data-root-host")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate aliases only; no operational Compose command",
    )
    parser.add_argument("compose_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    arguments = list(args.compose_args)
    if arguments[:1] == ["--"]:
        arguments.pop(0)
    if not arguments:
        arguments = ["config", "--quiet"]
    try:
        inputs = compose_inputs(arguments, Path.cwd())
        reject_indirect_selectors(inputs, os.environ)
        explicit = (
            {"CROW_DATA_ROOT_HOST": args.data_root_host} if args.data_root_host else {}
        )
        environment = resolve_environment(
            inputs.root, inputs.env_files, os.environ, explicit
        )
        reject_indirect_selectors(inputs, environment)
        if args.check:
            print("Crow Compose environment validated")
            return 0
        return subprocess.run(
            ["docker", "compose", *arguments], env=environment, check=False
        ).returncode
    except (EnvironmentAliasConflict, ComposeEnvironmentError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
