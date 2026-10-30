"""Manual-required transitions and compatibility flag publication."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from .archive_json_io import write_json
from .solver_manual_flags import global_manual_pause_active

if TYPE_CHECKING:
    from .runtime_state import RuntimeState
    from .solver_pause_cleanup import PauseSetter


class ManualFlagWriter(Protocol):
    def __call__(
        self, created_at_epoch: float, *, scope: str | None = None
    ) -> str | None: ...


def write_manual_flag(
    created_at_epoch: float,
    *,
    runtime: RuntimeState,
    path: str,
    scope: str | None,
    mirror_path: str | None = None,
    scope_flag_path: Callable[[str], str] | None = None,
    scope_state_path: Callable[[str], Path] | None = None,
) -> str | None:
    with runtime.lock:
        recovery = runtime.recovery.snapshot()
        state = runtime.control.scope_snapshot(scope) if scope else {}
        payload = {
            "manual_required": True,
            "manual_only": bool(state.get("manual_only", recovery.manual_only)),
            "scope": scope,
            "created_at_epoch": created_at_epoch,
            "last_request": dict(state.get("last_request", recovery.last_request)),
            "message": "Delete this file to force resume the queue after manual solving",
        }
        if not scope or not mirror_path or not scope_flag_path or not scope_state_path:
            return _publish(path, payload)
        # Capture existing global intent before replacing the scoped counterpart.
        preserve_global = global_manual_pause_active(
            mirror_path, scope_flag_path, scope_state_path
        )
        payload.update(
            flag_kind="scoped_manual_v1",
            owner_scope=scope,
            challenge_id=state.get("challenge_id"),
            publication_id=uuid4().hex,
        )
        error = _publish(path, payload)
        if preserve_global:
            return error
        mirror_error = _publish(
            mirror_path, dict(payload, flag_kind="scoped_manual_mirror_v1")
        )
        return error or mirror_error


def _publish(path: str, payload: Mapping[str, object]) -> str | None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        write_json(path, payload)
    except Exception as error:  # noqa: BLE001 - preserve flag publication error contract
        return repr(error)
    return None


def mark_manual_required(
    *,
    runtime: RuntimeState,
    scope: str | None,
    manual_only: bool,
    clock: Callable[[], float],
    cancel: Callable[[], None],
    persist_scope: Callable[[str, Mapping[str, object]], str | None],
    set_pause: PauseSetter,
    write_flag: ManualFlagWriter,
) -> str | None:
    with runtime.lock:
        solver_running = runtime.solver.require_manual()
        runtime.recovery.require_manual(clock(), manual_only=bool(manual_only))
        if solver_running:
            cancel()
        if scope:
            state = runtime.control.scope_snapshot(scope)
            state.update(
                paused=True,
                pause_reason="manual_required",
                manual_required=True,
                manual_only=bool(manual_only),
                last_status="manual_required",
                last_failure_reason="manual_required",
            )
            persist_error = persist_scope(scope, state)
        else:
            persist_error = None
        set_pause(True, "manual_required", scope=scope)
        error = write_flag(runtime.recovery.snapshot().required_epoch, scope=scope)
        return persist_error or error
