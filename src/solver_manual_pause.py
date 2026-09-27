"""Manual-required transitions and compatibility flag publication."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Protocol

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
) -> str | None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as flag_file:
            json.dump(
                {
                    "manual_required": True,
                    "manual_only": bool(runtime.recovery.snapshot().manual_only),
                    "scope": scope,
                    "created_at_epoch": created_at_epoch,
                    "last_request": dict(runtime.recovery.snapshot().last_request),
                    "message": "Delete this file to force resume the queue after manual solving",
                },
                flag_file,
                ensure_ascii=False,
            )
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
        with runtime.lock:
            state = runtime.control.scope_snapshot(scope)
            state.update(
                paused=True,
                pause_reason="manual_required",
                manual_required=True,
                manual_only=bool(manual_only),
                last_status="manual_required",
                last_failure_reason="manual_required",
            )
        persist_scope(scope, state)
    set_pause(True, "manual_required", scope=scope)
    error = write_flag(runtime.recovery.snapshot().required_epoch, scope=scope)
    if scope:
        # The scoped flag is authoritative; retain the legacy operator mirror too.
        legacy_error = write_flag(runtime.recovery.snapshot().required_epoch)
        return error or legacy_error
    return error
