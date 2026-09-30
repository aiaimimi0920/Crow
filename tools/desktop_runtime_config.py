"""Non-secret desktop installation settings; explicit environment wins."""

import json
import os
from pathlib import Path

from tools.pc1_desktop_recovery import RecoveryError

CONFIG_NAME = "crow-desktop.runtime.json"
PATH_KEYS = {
    "CROW_DATA_ROOT_HOST",
    "FAPAI_DATA_ROOT_HOST",
    "FAPAI_COOKIE_SNAPSHOT",
    "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE",
    "FAPAI_AUTH_BROWSER_PROFILE_DIR",
    "FAPAI_AUTH_BROWSER_PATH",
    "FAPAI_SETTINGS_CA_FILE",
    "FAPAI_ENGINE_OPERATOR_TOKEN_FILE",
    "FAPAI_API_CA_FILE",
    "FAPAI_DESKTOP_PYTHON_PATH",
}
ALLOWED_KEYS = PATH_KEYS | {
    "FAPAI_COLLECTOR_API_BASE",
    "FAPAI_AUTH_LOCAL_CDP_PORT",
    "FAPAI_SETTINGS_API_BASE",
}


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
        management_keys = {"CROW_DATA_ROOT_HOST", "FAPAI_DATA_ROOT_HOST"}
        process_management_root = any(environment.get(key) for key in management_keys)
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
            if key in management_keys and process_management_root:
                continue
            if not environment.get(key):
                environment[key] = value
        port = int(environment.get("FAPAI_AUTH_LOCAL_CDP_PORT") or 9225)
        if not 1024 <= port <= 65535:
            raise ValueError("port")
    except (ValueError, TypeError) as error:
        raise RecoveryError("runtime_config_invalid") from error
    return environment
