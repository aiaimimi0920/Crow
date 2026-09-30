"""Non-secret desktop installation settings; explicit environment wins."""

import json
import os
from pathlib import Path

from tools.pc1_desktop_recovery import RecoveryError
from tools.desktop_environment import ALLOWED_KEYS, PATH_KEYS, aliases, environment_value

CONFIG_NAME = "crow-desktop.runtime.json"


def load_runtime_environment(root, environ=None):
    """Only the selected bundle's config is trusted; never scan unrelated installs."""
    root = Path(root).resolve()
    path = root / CONFIG_NAME
    environment = dict(os.environ if environ is None else environ)
    try:
        with path.open("rb") as stream:
            raw = stream.read(16385)
    except FileNotFoundError:
        return environment
    except OSError as error:
        raise RecoveryError("runtime_config_invalid") from error
    try:
        if len(raw) > 16384:
            raise ValueError("oversized")
        config = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(config, dict)
            or set(config) != {"version", "environment"}
            or config["version"] != 1
        ):
            raise ValueError("schema")
        values = config["environment"]
        if not isinstance(values, dict) or set(values) - ALLOWED_KEYS:
            raise ValueError("fields")
        configured = {}
        for key, value in values.items():
            if (
                not isinstance(value, str)
                or not value.strip()
                or any(ord(char) < 32 for char in value)
            ):
                raise ValueError("value")
            if key in PATH_KEYS:
                candidate = Path(value)
                value = str(candidate if candidate.is_absolute() else root / candidate)
            configured[key] = value
        for canonical in {aliases(key)[0] for key in configured}:
            if environment_value(canonical, environment=environment, root=root):
                continue
            value = environment_value(canonical, environment=configured, root=root)
            if value is not None:
                for key in aliases(canonical):
                    environment[key] = value
        port = int(environment_value("CROW_AUTH_LOCAL_CDP_PORT", environment=environment, root=root) or 9225)
        if not 1024 <= port <= 65535:
            raise ValueError("port")
    except (ValueError, TypeError) as error:
        raise RecoveryError("runtime_config_invalid") from error
    return environment
