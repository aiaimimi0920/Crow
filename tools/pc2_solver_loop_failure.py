"""Persist failed attempts and optional manual escalation after target rotation."""

import time

from tools.pc2_reference_browse import maybe_browse_reference_tabs
from tools.pc2_solver_attempt_policy import (
    preserve_unconfirmed_target,
    safe_failure_reason,
)
from tools.pc2_solver_execution import rotate_failed_challenge_target
from tools.pc2_solver_failure_guard import failure_mutation_block_reason
from tools.pc2_solver_fallback import (
    FALLBACK_FAIL_THRESHOLD,
    FALLBACK_STALL_SECONDS,
    _manual_fallback_latch_active,
    _report_manual_captcha,
    manual_fallback_enabled,
)
from tools.pc2_solver_maintenance import (
    bind_pending_navigation,
    pending_navigation_probe,
)
from tools.pc2_solver_retry_state import (
    _record_slider_attempt_failure,
    _reset_fallback_state,
)
from tools.pc2_solver_state_store import _load_fallback_state, _save_fallback_state
from tools.pc2_solver_transport import log_event, read_solver_status


def log_solver_cooldown_started(state: dict[str, object], now: float) -> None:
    """Report the scheduled duration, including persisted exponential backoff."""
    log_event(
        {
            "kind": "solver_cooldown_started",
            "until": state["solver_cooldown_until"],
            "seconds": max(0.0, float(state["solver_cooldown_until"]) - now),
            "cycles": state.get("solver_cooldown_cycles", 0),
            "consecutive_failures": state.get("consecutive_failures", 0),
        }
    )


COOLDOWN_LOG_INTERVAL_SECONDS = 60.0


def log_solver_cooldown_active(
    state: dict[str, object],
    *,
    last_log: tuple[object, object, float] | None = None,
    now: float | None = None,
) -> tuple[object, object, float]:
    current = time.time() if now is None else float(now)
    key = (state.get("challenge_id"), state.get("solver_cooldown_until"))
    if (
        last_log is not None
        and (last_log[0], last_log[1]) == key
        and 0 <= current - last_log[2] < COOLDOWN_LOG_INTERVAL_SECONDS
    ):
        return last_log
    log_event(
        {
            "kind": "solver_cooldown_active",
            "until": state.get("solver_cooldown_until"),
            "reason": state.get("solver_cooldown_reason"),
            "consecutive_failures": state.get("consecutive_failures", 0),
        }
    )
    return (key[0], key[1], current)


def reconcile_manual_latch(
    fallback_state: dict[str, object], manual_required: bool
) -> bool:
    """Return True when the loop must continue waiting on an active manual latch."""
    if not fallback_state.get("manual_pushed"):
        return False
    if not manual_required:
        log_event({"kind": "fallback_manual_resolved"})
        _reset_fallback_state()
        return False
    if _manual_fallback_latch_active(fallback_state, manual_required):
        log_event(
            {
                "kind": "fallback_waiting_manual_auth",
                "manual_required": manual_required,
            }
        )
        return True
    log_event(
        {
            "kind": "fallback_manual_latch_bypassed",
            "manual_required": manual_required,
        }
    )
    _reset_fallback_state()
    return False


def record_failed_attempt(
    api_base_url: str,
    cdp_endpoint: str,
    target_url: str,
    probe_target: dict[str, object] | None,
    *,
    failure_reason: object = None,
    solver_status: dict[str, object] | None = None,
    expected_node_id: str | None = None,
) -> dict[str, object] | None:
    failure_reason = safe_failure_reason(failure_reason)
    preserve_target = preserve_unconfirmed_target(failure_reason)
    log_event({"kind": "local_solver_failure", "failure_reason": failure_reason})
    # Account the completed attempt before fallible control reads or page rotation.
    state = _load_fallback_state()
    now = time.time()
    failure = _record_slider_attempt_failure(state, now=now)
    last_success_at = float(state.get("last_success_at") or 0) or None
    window_started_at = float(state.get("window_started_at") or 0) or now
    stalled_seconds = (
        now - window_started_at
        if last_success_at is None
        else now - max(last_success_at, window_started_at)
    )
    threshold_reached = int(state["slider_attempts"]) >= FALLBACK_FAIL_THRESHOLD
    stalled = stalled_seconds >= FALLBACK_STALL_SECONDS
    cooldown_started = bool(failure.get("cooldown_started"))
    state["stalled_seconds"] = round(stalled_seconds, 1)
    state["threshold_reached"] = threshold_reached
    state["stalled"] = stalled
    _save_fallback_state(state)
    log_event(
        {
            "kind": "slider_attempt_failed",
            "attempt": state["slider_attempts"],
            "next_attempt_at": state.get("slider_next_attempt_at"),
            "cooldown_until": state.get("solver_cooldown_until"),
        }
    )
    if cooldown_started:
        log_solver_cooldown_started(state, now)
    mutation_block_reason = None
    if not preserve_target and isinstance(solver_status, dict):
        mutation_block_reason = failure_mutation_block_reason(
            solver_status,
            read_solver_status(api_base_url),
            target_url,
            cdp_endpoint,
            expected_node_id,
        )
    rotation = (
        {
            "attempted": False,
            "opened": False,
            "closed": 0,
            "reason": mutation_block_reason or "unconfirmed_attempt_target_preserved",
            "probe_target": None if mutation_block_reason else probe_target,
        }
        if preserve_target or mutation_block_reason
        else rotate_failed_challenge_target(
            cdp_endpoint,
            target_url,
            probe_target=probe_target,
            open_replacement=not cooldown_started,
        )
    )
    rotated_probe = rotation.get("probe_target")
    navigation_pending = pending_navigation_probe(rotated_probe)
    last_probe_target = (
        bind_pending_navigation(rotated_probe, state.get("challenge_id"))
        if isinstance(rotated_probe, dict)
        else None
    )
    log_event(
        {
            "kind": "failed_challenge_target_rotation",
            "attempted": rotation.get("attempted"),
            "opened": rotation.get("opened"),
            "closed": rotation.get("closed", 0),
            "scope": rotation.get("scope"),
            "reason": rotation.get("reason"),
            "error_type": rotation.get("error_type"),
        }
    )
    should_push = bool(
        manual_fallback_enabled()
        and not preserve_target
        and not navigation_pending
        and not mutation_block_reason
        and threshold_reached
        and stalled
        and not state.get("manual_pushed")
    )
    log_event(
        {
            "kind": "pc1_manual_escalation_check",
            "consecutive_failures": state["consecutive_failures"],
            "stalled_seconds": round(stalled_seconds, 1),
            "threshold": FALLBACK_FAIL_THRESHOLD,
            "stalled_threshold_seconds": FALLBACK_STALL_SECONDS,
            "should_push": should_push,
            "manual_pushed": state.get("manual_pushed", False),
        }
    )
    if should_push:
        manual_result = _report_manual_captcha(api_base_url, cdp_endpoint, target_url)
        state["manual_pushed"] = True
        state["manual_pushed_at_epoch"] = time.time()
        state["manual_result"] = manual_result
        _save_fallback_state(state)
        log_event({"kind": "pc1_manual_auth_pushed", "result": manual_result})
    if (
        not should_push
        and not cooldown_started
        and not preserve_target
        and not navigation_pending
        and not mutation_block_reason
    ):
        maybe_browse_reference_tabs(api_base_url, cdp_endpoint, last_probe_target)
    return last_probe_target
