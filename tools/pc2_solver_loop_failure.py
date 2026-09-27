"""Persist failed attempts and optional manual escalation after target rotation."""

import time

from tools.pc2_solver_execution import rotate_failed_challenge_target
from tools.pc2_solver_fallback import (
    FALLBACK_FAIL_THRESHOLD,
    FALLBACK_STALL_SECONDS,
    _report_manual_captcha,
    manual_fallback_enabled,
)
from tools.pc2_solver_retry_state import (
    SOLVER_COOLDOWN_SECONDS,
    _record_slider_attempt_failure,
)
from tools.pc2_solver_state_store import _load_fallback_state, _save_fallback_state
from tools.pc2_solver_transport import log_event


def record_failed_attempt(
    api_base_url: str,
    cdp_endpoint: str,
    target_url: str,
    probe_target: dict[str, object] | None,
) -> dict[str, object] | None:
    log_event({"kind": "local_solver_failure"})
    rotation = rotate_failed_challenge_target(
        cdp_endpoint, target_url, probe_target=probe_target
    )
    rotated_probe = rotation.get("probe_target")
    last_probe_target = rotated_probe if isinstance(rotated_probe, dict) else None
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
    should_push = bool(
        manual_fallback_enabled()
        and threshold_reached
        and stalled
        and not state.get("manual_pushed")
    )
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
    if cooldown_started:
        log_event(
            {
                "kind": "solver_cooldown_started",
                "until": state["solver_cooldown_until"],
                "seconds": max(0.0, SOLVER_COOLDOWN_SECONDS),
                "consecutive_failures": state["consecutive_failures"],
            }
        )
    if should_push:
        manual_result = _report_manual_captcha(api_base_url, cdp_endpoint, target_url)
        state["manual_pushed"] = True
        state["manual_pushed_at_epoch"] = time.time()
        state["manual_result"] = manual_result
        _save_fallback_state(state)
        log_event({"kind": "pc1_manual_auth_pushed", "result": manual_result})
    return last_probe_target
