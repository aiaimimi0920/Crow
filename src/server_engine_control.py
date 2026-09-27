from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from . import collection_engine_restart as _engine_control
from .collection_control_state import CHALLENGE_SCOPES
from .server_request_guard import _read_limited_body

if TYPE_CHECKING:
    from .runtime_state import RuntimeState


def _engine_restart_mailbox() -> _engine_control.RestartMailbox:
    return _engine_control.RestartMailbox(_engine_control.runtime_root())


def _engine_restart_status(
    *, mailbox_factory: Callable[[], Any] | None = None
) -> dict[str, Any]:
    if not _engine_control.configured():
        return {"available": False, "request": None}
    try:
        factory = mailbox_factory or _engine_restart_mailbox
        return cast(dict[str, Any], factory().status())
    except (OSError, _engine_control.sqlite3.Error):
        return {"available": False, "request": None}


def _collection_operator_start(
    *,
    runtime: RuntimeState,
    set_pause_state: Callable[..., None],
    scope_status: Callable[[str], dict[str, Any]],
    runtime_state_label: Callable[[], str],
) -> dict[str, Any]:
    # Starting collection is not proof that an authentication challenge was solved.
    with runtime.lock:
        control = runtime.control.snapshot()
        solver = runtime.solver.snapshot()
    if control.paused and control.reason in (None, "operator"):
        if solver.last_status == "manual_required":
            set_pause_state(True, "manual_required")
        elif any(scope_status(scope).get("paused") for scope in CHALLENGE_SCOPES):
            set_pause_state(True, "captcha_solver")
        else:
            set_pause_state(False)
    return {"ok": True, "action": "start", "runtime_state": runtime_state_label()}


def _server_engine_control(
    handler: Any,
    *,
    collection_operator_start: Callable[[], dict[str, Any]],
    mailbox_factory: Callable[[], Any] | None = None,
) -> None:
    path = urlparse(handler.path).path
    role = "operator" if path == _engine_control.PREFIX else "agent"
    try:
        _engine_control.authorize(handler.headers, role)
        try:
            body = _read_limited_body(handler, max_bytes=4096, min_bytes=2)
        except ValueError as error:
            raise _engine_control.RestartError(
                "Invalid request body length", 400
            ) from error
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise _engine_control.RestartError("Request body must be an object", 400)
        mailbox = (mailbox_factory or _engine_restart_mailbox)()
        if path == _engine_control.PREFIX:
            if set(payload) != {"request_id"}:
                raise _engine_control.RestartError("Only request_id is accepted", 400)
            result = mailbox.request(payload.get("request_id"))
            if result["created"]:
                # Resume once, at acceptance. Later receipts must not undo a newer operator pause.
                try:
                    collection_operator_start()
                except (
                    AttributeError,
                    KeyError,
                    OSError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                ):
                    result["warning"] = (
                        "Restart accepted, but collection resume was not confirmed; check the start/pause control"
                    )
        elif path.endswith("/poll"):
            if payload:
                raise _engine_control.RestartError("Poll body must be empty", 400)
            result = mailbox.poll()
        else:
            if set(payload) != {"request_id", "claim", "result"}:
                raise _engine_control.RestartError("Invalid result fields", 400)
            result = mailbox.finish(payload)
        handler.send_json(result)
    except _engine_control.RestartError as error:
        handler.send_error_json(
            status=error.status,
            code="ENGINE_RESTART_REJECTED",
            message=str(error),
            details={},
        )
    except (ValueError, UnicodeError):
        handler.send_error_json(
            status=400,
            code="ENGINE_RESTART_INVALID_JSON",
            message="Invalid request body",
            details={},
        )
    except (OSError, _engine_control.sqlite3.Error):
        handler.send_error_json(
            status=503,
            code="ENGINE_RESTART_STORAGE_UNAVAILABLE",
            message="Restart mailbox unavailable",
            details={},
        )


__all__ = [
    "_collection_operator_start",
    "_engine_control",
    "_engine_restart_mailbox",
    "_engine_restart_status",
    "_server_engine_control",
]
