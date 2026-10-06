"""Native challenge and slider retry state transitions."""

from __future__ import annotations

import time
from typing import cast

from src.project_environment import getenv as project_getenv
from tools.pc2_solver_config import (
    AUTH_COMPLETE_RETRY_BASE_SECONDS,
    AUTH_COMPLETE_RETRY_MAX_SECONDS,
)
from tools.pc2_solver_state_store import _default_fallback_state, _save_fallback_state

SOLVER_COOLDOWN_FAIL_THRESHOLD = int(
    project_getenv("CROW_SOLVER_COOLDOWN_FAIL_THRESHOLD", "10")
)
SOLVER_COOLDOWN_SECONDS = float(project_getenv("CROW_SOLVER_COOLDOWN_SECONDS", "180"))
SLIDER_RETRY_INTERVAL_SECONDS = float(
    project_getenv("CROW_SLIDER_RETRY_INTERVAL_SECONDS", "5")
)


def _auth_complete_retry_delay(attempts: int | None) -> float:
    exponent = max(0, min(int(attempts or 0) - 1, 6))
    return cast(
        float,
        min(
            max(AUTH_COMPLETE_RETRY_BASE_SECONDS, 0.0) * (2**exponent),
            max(AUTH_COMPLETE_RETRY_MAX_SECONDS, 0.0),
        ),
    )


def _browser_backpressure(state: dict[str, object]) -> dict[str, object]:
    budget = {
        key: state.get(key)
        for key in (
            "window_started_at",
            "slider_next_attempt_at",
            "solver_cooldown_until",
            "solver_cooldown_reason",
        )
    }
    budget["consecutive_failures"] = max(
        int(cast("str | int", state.get("consecutive_failures") or 0)),
        int(cast("str | int", state.get("slider_attempts") or 0)),
    )
    return budget


def _reset_fallback_state(
    *, preserve_budget_from: dict[str, object] | None = None
) -> dict[str, object]:
    """Full reset by default; automatic expiry can retain backpressure and lineage."""
    state: dict[str, object] = _default_fallback_state()
    if (
        preserve_budget_from is not None
        and preserve_budget_from.get("scope") in {"seed", "detail"}
        and str(preserve_budget_from.get("challenge_id") or "").strip()
    ):
        state.update(
            _browser_backpressure(preserve_budget_from),
            challenge_id=preserve_budget_from["challenge_id"],
            scope=preserve_budget_from["scope"],
        )
    _save_fallback_state(state)
    return state


def _sync_challenge_state(
    state: dict[str, object], challenge_id: object, scope: object = None
) -> tuple[dict[str, object], bool]:
    challenge_id = str(challenge_id or "").strip()
    if not challenge_id:
        return state, False
    normalized_scope = str(scope or "").strip() or None
    current_id = str(state.get("challenge_id") or "").strip()
    if current_id == challenge_id:
        if normalized_scope and state.get("scope") != normalized_scope:
            state["scope"] = normalized_scope
            _save_fallback_state(state)
        return state, False
    if current_id:
        # Generation-local receipts expire; shared-browser backpressure does not.
        previous = state
        state = _default_fallback_state()
        if previous.get("scope") in {"seed", "detail"} and normalized_scope in {
            "seed",
            "detail",
        }:
            state.update(_browser_backpressure(previous))
    state["challenge_id"] = challenge_id
    state["scope"] = normalized_scope
    _save_fallback_state(state)
    return state, bool(current_id)


def _solver_cooldown_active(state: object, now: float | None = None) -> bool:
    """Return whether the persisted solver retry cooldown is still active."""
    if not isinstance(state, dict):
        return False
    current_time = time.time() if now is None else float(now)
    cooldown_until = float(state.get("solver_cooldown_until") or 0)
    return cooldown_until > current_time


def _node_solver_cooldown_matches(
    state: dict[str, object], status: dict[str, object]
) -> bool:
    """Match automatic backpressure without treating server state as a report ACK."""
    return bool(
        status.get("node_solver_blocked")
        and status.get("last_failure_reason") == "repeated_solver_failures"
        and state.get("solver_cooldown_reason") == "repeated_solver_failures"
        and state.get("solver_cooldown_until")
        and state.get("challenge_id")
        and state.get("challenge_id") == status.get("challenge_id")
        and state.get("scope") == status.get("scope")
        and not state.get("terminal_manual_pending")
        and not state.get("manual_pushed")
    )


def _node_solver_cooldown_can_resume(
    state: dict[str, object], status: dict[str, object]
) -> bool:
    """An automatic blocked report must not turn its cooldown into a manual latch."""
    return bool(
        state.get("node_solver_blocked_reported")
        and _node_solver_cooldown_matches(state, status)
    )


def _begin_solver_cooldown_if_needed(
    state: dict[str, object], now: float | None = None
) -> bool:
    if not isinstance(state, dict) or state.get("solver_cooldown_until"):
        return False
    failures = max(
        int(cast("str | int", state.get("slider_attempts") or 0)),
        int(cast("str | int", state.get("consecutive_failures") or 0)),
    )
    threshold = max(1, SOLVER_COOLDOWN_FAIL_THRESHOLD)
    cooldown_seconds = max(0.0, SOLVER_COOLDOWN_SECONDS)
    if failures < threshold or cooldown_seconds <= 0:
        return False
    current_time = time.time() if now is None else float(now)
    state["solver_cooldown_until"] = current_time + cooldown_seconds
    state["solver_cooldown_reason"] = "repeated_solver_failures"
    state["slider_next_attempt_at"] = None
    return True


def _slider_retry_due(state: dict[str, object], now: float | None = None) -> bool:
    current_time = time.time() if now is None else float(now)
    return (
        float(cast("str | float", state.get("slider_next_attempt_at") or 0))
        <= current_time
    )


def _record_slider_attempt_started(
    state: dict[str, object], now: float | None = None
) -> dict[str, object]:
    current_time = time.time() if now is None else float(now)
    state["slider_attempt_started_at"] = current_time
    state["slider_last_progress_at"] = current_time
    _save_fallback_state(state)
    return state


def _record_slider_attempt_failure(
    state: dict[str, object], now: float | None = None
) -> dict[str, object]:
    current_time = time.time() if now is None else float(now)
    attempts = int(cast("str | int", state.get("slider_attempts", 0) or 0)) + 1
    failures = (
        max(
            attempts - 1,
            int(cast("str | int", state.get("consecutive_failures") or 0)),
        )
        + 1
    )
    state["slider_attempts"] = attempts
    state["consecutive_failures"] = failures
    state["slider_attempt_started_at"] = None
    state["slider_last_progress_at"] = current_time
    if not state.get("window_started_at"):
        state["window_started_at"] = current_time
    cooldown_started = _begin_solver_cooldown_if_needed(state, now=current_time)
    if not cooldown_started:
        state["slider_next_attempt_at"] = current_time + max(
            0.0, SLIDER_RETRY_INTERVAL_SECONDS
        )
    return {
        "attempts": attempts,
        "cooldown_started": cooldown_started,
        "next_attempt_at": state.get("slider_next_attempt_at"),
        "cooldown_until": state.get("solver_cooldown_until"),
    }


__all__ = (
    "SLIDER_RETRY_INTERVAL_SECONDS",
    "SOLVER_COOLDOWN_FAIL_THRESHOLD",
    "SOLVER_COOLDOWN_SECONDS",
    "_auth_complete_retry_delay",
    "_begin_solver_cooldown_if_needed",
    "_node_solver_cooldown_can_resume",
    "_record_slider_attempt_failure",
    "_record_slider_attempt_started",
    "_reset_fallback_state",
    "_slider_retry_due",
    "_solver_cooldown_active",
    "_sync_challenge_state",
)
