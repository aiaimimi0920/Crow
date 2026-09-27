"""Restore auth cleanup after completion receipt publication fails."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .collection_control_state import CHALLENGE_SCOPES, new_scope_state

if TYPE_CHECKING:
    from .runtime_state import RuntimeState
    from .solver_recovery_state import SolverRecoverySnapshot


def restore_legacy_manual_pause(runtime: RuntimeState, flag_path: Path) -> bool:
    """Hydrate matching durable manual metadata without rewriting legacy files."""
    try:
        payload = json.loads(flag_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Older installations also use opaque flag files; existence still pauses.
        return False
    if not isinstance(payload, dict) or payload.get("manual_required") is not True:
        return False
    required_epoch = payload.get("created_at_epoch")
    manual_only = payload.get("manual_only")
    if (
        isinstance(required_epoch, bool)
        or not isinstance(required_epoch, (int, float))
        or not math.isfinite(required_epoch)
        or required_epoch < 0
        or not isinstance(manual_only, bool)
    ):
        return False
    with runtime.lock:
        recovery = runtime.recovery.snapshot()
        if (
            not recovery.challenge_id
            or payload.get("last_request") != recovery.last_request
        ):
            return False
        runtime.recovery.require_manual(required_epoch, manual_only=manual_only)
        runtime.solver.record_outcome("manual_required", "manual_required")
    return True


def legacy_cleanup_state(
    recovery: SolverRecoverySnapshot, *, manual_only: bool = False
) -> dict[str, object]:
    state: dict[str, object] = new_scope_state()
    state.update(
        challenge_id=recovery.challenge_id,
        last_request=dict(recovery.last_request),
        paused=True,
        pause_reason="manual_required",
        manual_required=True,
        manual_only=recovery.manual_only or manual_only,
        resume_epoch=recovery.resume_epoch,
        required_epoch=recovery.required_epoch,
    )
    return state


def restore_legacy_cleanup(
    state: Mapping[str, object],
    *,
    runtime: RuntimeState,
    persist_legacy: Callable[[str, dict[str, str]], str | None],
    write_manual_flag: Callable[[float], str | None],
) -> str | None:
    """Restore a validated journal before startup can launch workers."""
    with runtime.lock:
        challenge_id = cast("str", state["challenge_id"])
        request = dict(cast("Mapping[str, str]", state["last_request"]))
        required_epoch = cast("float", state["required_epoch"])
        runtime.recovery.set_challenge(challenge_id, request)
        runtime.recovery.resume(cast("float", state["resume_epoch"]))
        runtime.recovery.require_manual(
            required_epoch, manual_only=bool(state["manual_only"])
        )
        runtime.control.set_pause(True, "manual_required")
        runtime.solver.record_outcome("manual_required", "manual_required")
        receipt_error = persist_legacy(challenge_id, request)
        flag_error = write_manual_flag(required_epoch)
        return (
            "; ".join(error for error in (receipt_error, flag_error) if error) or None
        )


def restore_auth_cleanup(
    scope: str | None,
    scoped_state: Mapping[str, object],
    recovery: SolverRecoverySnapshot,
    *,
    runtime: RuntimeState,
    persist_scope: Callable[[str, Mapping[str, object]], str | None],
    persist_legacy: Callable[[str, dict[str, str]], str | None],
    write_manual_flag: Callable[[float], str | None],
) -> str | None:
    """Caller holds runtime.lock from checkpoint capture through rollback."""
    with runtime.lock:
        scoped = scope is not None and scope in CHALLENGE_SCOPES
        if scope is not None and scoped:
            runtime.control.set_scope(scope, scoped_state)
        runtime.recovery.set_challenge(recovery.challenge_id, recovery.last_request)
        runtime.recovery.resume(recovery.resume_epoch)
        runtime.recovery.require_manual(
            recovery.required_epoch,
            manual_only=recovery.manual_only
            if scoped
            else bool(scoped_state.get("manual_only", recovery.manual_only)),
        )
        recovery_error = None
        if scope is not None and scoped:
            recovery_error = persist_scope(scope, scoped_state)
        elif recovery.challenge_id:
            recovery_error = persist_legacy(
                recovery.challenge_id, recovery.last_request
            )
        if not scoped or recovery_error:
            # Legacy receipts do not encode manual-only state; restore their flag too.
            flag_error = write_manual_flag(recovery.required_epoch)
            if flag_error:
                recovery_error = "; ".join(
                    error
                    for error in (recovery_error, f"manual flag: {flag_error}")
                    if error
                )
        return recovery_error
