"""Check final container alias values without rewriting Compose's layer priority."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence

from src.project_environment import EnvironmentAliasConflict, getenv
from tools.compose_arguments import ComposeEnvironmentError


def validate_service_environment(
    global_arguments: Sequence[str],
    environment: Mapping[str, str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    # Caller supplies the same already-validated global prefix, never up/exec args.
    command = ["docker", "compose", *global_arguments, "config", "--format", "json"]
    try:
        result = runner(
            command,
            env=dict(environment),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise ComposeEnvironmentError(
                "Final Compose configuration validation failed"
            )
        model = json.loads(result.stdout)
        if not isinstance(model, dict) or "services" not in model:
            raise TypeError("missing services")
        services = model["services"]
        if not isinstance(services, dict):
            raise TypeError("invalid services")
        for service in services.values():
            values = service.get("environment", {})
            if not isinstance(values, dict) or any(
                not isinstance(key, str)
                or (value is not None and not isinstance(value, str))
                for key, value in values.items()
            ):
                raise ValueError("invalid environment")
            for key in values:
                if key.startswith(("CROW_", "FAPAI_")):
                    getenv(key, reader=values.get)
    except EnvironmentAliasConflict as error:
        raise ComposeEnvironmentError(
            str(error)
            + "; container env_file settings overridden by service.environment must retain the legacy wire keys"
        ) from None
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        AttributeError,
        TypeError,
    ) as error:
        if isinstance(error, ComposeEnvironmentError):
            raise
        raise ComposeEnvironmentError(
            "Final Compose configuration validation unavailable"
        ) from None
