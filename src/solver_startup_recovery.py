"""Restore startup challenge ownership using explicit runtime dependencies."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .auth_cleanup_recovery import restore_legacy_manual_pause
from .collection_control_state import CHALLENGE_SCOPES

if TYPE_CHECKING:
    from .runtime_state import RuntimeState
    from .solver_pause_cleanup import PauseSetter


def restore_legacy_challenge(
    *,
    runtime: RuntimeState,
    read_legacy: Callable[[], Mapping[str, object]],
    manual_flag_path: Callable[[], str],
    set_pause: PauseSetter,
) -> bool:
    payload = read_legacy()
    if not payload:
        return False
    persisted_request = payload.get("last_request")
    with runtime.lock:
        runtime.recovery.set_challenge(
            cast("str", payload["challenge_id"]),
            cast("dict[str, str]", persisted_request)
            if isinstance(persisted_request, dict) and persisted_request
            else None,
        )
        manual = restore_legacy_manual_pause(runtime, Path(manual_flag_path()))
        set_pause(
            True,
            "manual_required"
            if manual
            else str(payload.get("pause_reason") or "captcha_solver"),
        )
    return True


def restore_scoped_challenges(
    *,
    runtime: RuntimeState,
    read_scope: Callable[[str], Mapping[str, object]],
    set_pause: PauseSetter,
) -> bool:
    restored = False
    for scope in CHALLENGE_SCOPES:
        state = read_scope(scope)
        if not state.get("challenge_id"):
            continue
        with runtime.lock:
            runtime.control.set_scope(scope, state)
            set_pause(
                True, str(state.get("pause_reason") or "captcha_solver"), scope=scope
            )
            if not runtime.recovery.snapshot().challenge_id:
                runtime.recovery.set_challenge(
                    str(state.get("challenge_id")),
                    dict(cast("Mapping[str, str]", state.get("last_request") or {})),
                )
        restored = True
    return restored
