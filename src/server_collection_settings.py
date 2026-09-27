"""Settings HTTP transport with module-owned storage and authorization dependencies."""

import json
from typing import Protocol
from urllib.parse import urlparse

from src import collection_engine_restart as _settings_auth
from src import collection_settings_schema as _settings_schema
from src import collection_settings_store as _settings_store
from src.server_request_guard import GuardRequest, _read_limited_body


class SettingsRequest(GuardRequest, Protocol):
    path: str

    def send_json(self, data: object) -> None: ...


def _collection_settings_store() -> _settings_store.SettingsStore:
    return _settings_store.SettingsStore(_settings_auth.runtime_root())


def _server_collection_settings(
    handler: SettingsRequest, *, read: bool = False
) -> None:
    path = urlparse(handler.path).path
    try:
        role = _settings_schema.ROLES.get(path)
        if (
            role is None
            or (read and path != _settings_schema.PREFIX)
            or (not read and path == _settings_schema.PREFIX)
        ):
            raise _settings_auth.RestartError("Unsupported settings route", 404)
        _settings_auth.authorize(handler.headers, role)
        store = _collection_settings_store()
        if read:
            result = store.status()
        else:
            try:
                body = _read_limited_body(handler, max_bytes=16384, min_bytes=2)
            except ValueError as error:
                raise _settings_auth.RestartError(
                    "Invalid settings body length", 400
                ) from error
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise _settings_auth.RestartError("Expected a settings object", 400)
            action = path.rsplit("/", 1)[-1]
            result = {"apply": store.apply, "poll": store.poll, "result": store.finish}[
                action
            ](payload)
        handler.send_json(result)
    except _settings_auth.RestartError as error:
        handler.send_error_json(
            status=error.status,
            code="SETTINGS_REJECTED",
            message=str(error),
            details={},
        )
    except (ValueError, UnicodeError, TypeError):
        handler.send_error_json(
            status=400,
            code="SETTINGS_INVALID",
            message="Invalid settings request",
            details={},
        )
    except (OSError, _settings_store.sqlite3.Error):
        handler.send_error_json(
            status=503,
            code="SETTINGS_UNAVAILABLE",
            message="Settings storage unavailable",
            details={},
        )


__all__ = [
    "_settings_schema",
    "_settings_store",
    "_settings_auth",
    "_collection_settings_store",
    "_server_collection_settings",
]
