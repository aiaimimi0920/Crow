"""Clear one auth pause without releasing a different challenge's global latch."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .runtime_state import RuntimeState


class PauseSetter(Protocol):
    def __call__(
        self, paused: bool, reason: str | None = None, *, scope: str | None = None
    ) -> None: ...


def independent_global_pause(
    scope: str | None,
    target_id: object,
    legacy_id: object,
    recovery_id: object,
    flag_scope: str | None,
) -> bool:
    return bool(
        scope
        and (
            any(owner and owner != target_id for owner in (legacy_id, recovery_id))
            or (flag_scope and flag_scope != scope)
        )
    )


def clear_automated_pause(
    *,
    runtime: RuntimeState,
    scope: str | None,
    infer_scope: Callable[[dict[str, str]], str | None],
    read_scope: Callable[[str], Mapping[str, object]],
    read_legacy: Callable[[], Mapping[str, object]],
    flag_path: Callable[[], str],
    flag_scope: Callable[[], str | None],
    scoped_flag_path: Callable[[str], str],
    clear_scoped_pause: Callable[[str], str | None],
    clear_challenge: Callable[[str | None], str | None],
    set_pause: PauseSetter,
    remember_completion: Callable[[dict[str, str]], None],
    logger: logging.Logger,
) -> None:
    with runtime.lock:
        recovery = runtime.recovery.snapshot()
        scope = scope or infer_scope(recovery.last_request)
        target_id = read_scope(scope).get("challenge_id") if scope else None
        if independent_global_pause(
            scope,
            target_id,
            read_legacy().get("challenge_id"),
            recovery.challenge_id,
            flag_scope(),
        ):
            # The singleton belongs to another challenge; do not publish this
            # scope's success into its outcome or authentication grace metadata.
            assert scope is not None
            error = clear_scoped_pause(scope)
            if error:
                logger.error("[SOLVER] Failed to clear scoped auth pause: %s", error)
            return
        challenge_error = clear_challenge(scope)
        if challenge_error:
            runtime.solver.record_outcome("manual_required", "manual_required")
            set_pause(True, "manual_required", scope=scope)
            logger.error(
                "[SOLVER] Failed to clear persisted challenge state after success: %s",
                challenge_error,
            )
            return
        runtime.solver.record_outcome("solved")
        runtime.recovery.clear_manual()
        runtime.recovery.resume(time.time())
        remember_completion(dict(recovery.last_request))
        if scope:
            set_pause(False, scope=scope)
        else:
            control = runtime.control.snapshot()
            if control.paused and control.reason in {
                None,
                "captcha_solver",
                "manual_required",
            }:
                set_pause(False)
        path = flag_path()
        owner_scope = flag_scope()
        if os.path.exists(path) and (
            not scope or not owner_scope or owner_scope == scope
        ):
            try:
                os.remove(path)
                logger.info(
                    "[SOLVER] Cleared force_unlock.flag after automated captcha success."
                )
            except Exception:
                logger.exception(
                    "[SOLVER] Failed to remove force_unlock.flag after success"
                )
        if scope:
            try:
                Path(scoped_flag_path(scope)).unlink(missing_ok=True)
            except Exception:
                logger.exception(
                    "[SOLVER] Failed to remove scoped manual flag after success"
                )


def clear_manual_pause(
    *,
    runtime: RuntimeState,
    scope: str | None,
    preserve_running_state: bool,
    flag_path: str,
    flag_scope: str | None,
    scoped_flag_path: Callable[[str], str],
    read_scope: Callable[[str], Mapping[str, object]],
    read_legacy: Callable[[], Mapping[str, object]],
    clear_challenge: Callable[[str | None], str | None],
    set_pause: PauseSetter,
    clear_running: Callable[[], None],
    clear_manual: Callable[[], None],
) -> str | None:
    with runtime.lock:
        target_id = read_scope(scope).get("challenge_id") if scope else None
        preserve_global = independent_global_pause(
            scope,
            target_id,
            read_legacy().get("challenge_id"),
            runtime.recovery.snapshot().challenge_id,
            flag_scope,
        )
        if os.path.exists(flag_path) and not preserve_global:
            try:
                os.remove(flag_path)
            except Exception as error:  # noqa: BLE001 - preserve cleanup error contract
                return str(error)
        if scope:
            try:
                Path(scoped_flag_path(scope)).unlink(missing_ok=True)
            except Exception as error:  # noqa: BLE001 - preserve cleanup error contract
                return str(error)
        challenge_error = clear_challenge(scope)
        if challenge_error:
            return challenge_error
        # Scoped challenge clearing already resets its pause. Do not let the
        # aggregate pause setter or singleton cleanup release another owner.
        if preserve_global:
            return None
        set_pause(False, scope=scope)
        runtime.recovery.resume(time.time())
        runtime.solver.cancel()
        if not preserve_running_state:
            clear_running()
        clear_manual()
    return None
