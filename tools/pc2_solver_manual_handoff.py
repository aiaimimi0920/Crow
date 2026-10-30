"""Manual handoff receipts and blocked-execution reporting."""

import time
from collections.abc import Callable, Mapping
from typing import TypeVar, cast

from tools.pc2_solver_scope_policy import manual_challenge_registration_needed

_AttemptResult = TypeVar("_AttemptResult")


class ManualChallengeRequired(RuntimeError):
    pass


def retry_terminal_manual_report(
    state: dict[str, object],
    solver_status: Mapping[str, object],
    report: Callable[[], Mapping[str, object]],
    save: Callable[[dict[str, object]], None],
    *,
    now: float | None = None,
) -> bool:
    if not state.get("terminal_manual_pending"):
        return False
    if solver_status.get("paused") is False and solver_status.get("last_status") in {
        "manual_auth_completed",
        "resumed_after_cooldown",
        "resumed",
        "solved",
    }:
        state["terminal_manual_pending"] = False
        save(state)
        return False
    now = time.time() if now is None else now
    if solver_status.get("manual_required"):
        state["terminal_manual_pending"] = False
        state["manual_pushed"] = True
        save(state)
        return True
    if now < cast(float, state.get("terminal_manual_next_report", 0)):
        return True
    # Persist the latch before network I/O; an unavailable NAS must not restart solving.
    state["terminal_manual_next_report"] = now + 30
    save(state)
    result = report()
    if result.get("status") == "manual_required":
        state["terminal_manual_pending"] = False
        state["manual_pushed"] = True
        save(state)
    return True


def attempt_or_manual_handoff(
    attempt: Callable[[], _AttemptResult],
    state: dict[str, object],
    status: Mapping[str, object],
    report: Callable[[], Mapping[str, object]],
    save: Callable[[dict[str, object]], None],
) -> _AttemptResult | None:
    try:
        return attempt()
    except ManualChallengeRequired:
        state["terminal_manual_pending"] = True
        state["terminal_manual_next_report"] = 0
        save(state)
        retry_terminal_manual_report(state, status, report, save)
        return None


def report_execution_block(
    reason: str,
    status: dict[str, object],
    report: Callable[[], Mapping[str, object]],
    emit: Callable[[dict[str, object]], None],
) -> None:
    """Preserve manual registration and its receipt before the blocked event."""
    if reason == "manual_only" and manual_challenge_registration_needed(status):
        result = report()
        solver = result.get("captcha_solver")
        emit(
            {
                "kind": "manual_challenge_reported",
                "status": result.get("status"),
                "ok": result.get("ok"),
                "error": result.get("error"),
                "challenge_id": solver.get("challenge_id")
                if isinstance(solver, dict)
                else None,
            }
        )
    emit({"kind": "local_solver_execution_blocked", "reason": reason})


__all__ = (
    "ManualChallengeRequired",
    "attempt_or_manual_handoff",
    "report_execution_block",
    "retry_terminal_manual_report",
)
