from __future__ import annotations

import time
import traceback
from functools import partial

from tools.pc2_solver_auth import (
    _post_auth_cdp_probe_grace_active,
)
from tools.pc2_solver_auth_pending import (
    confirm_local_solver_success,
)
from tools.pc2_solver_cdp import (
    match_solver_request_target_url,
)
from tools.pc2_solver_config import (
    DEFAULT_API_BASE_URL,
    DEFAULT_CDP_ENDPOINT,
    DEFAULT_DRAG_PROFILE_VARIANTS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_POLL_SECONDS,
)
from tools.pc2_solver_execution import (
    close_stale_challenge_probe_target,
    resolve_stale_challenge_probe_target_after_resume,
    run_solver_local_with_deadline,
)
from tools.pc2_solver_fallback import (
    _manual_fallback_latch_active,
    _mark_collection_resume_pending,
    _retry_node_solver_blocked_report,
    _retry_pending_collection_resume,
)
from tools.pc2_solver_loop_control import (
    process_pending_control_actions,
    recover_stale_pause,
    reset_forced_solver_scopes,
)
from tools.pc2_solver_loop_failure import record_failed_attempt
from tools.pc2_solver_loop_probe import prepare_solver_browser, probe_requested_targets
from tools.pc2_solver_manual_handoff import (
    attempt_or_manual_handoff,
    retry_terminal_manual_report,
)
from tools.pc2_solver_retry_state import (
    SOLVER_COOLDOWN_FAIL_THRESHOLD,
    SOLVER_COOLDOWN_SECONDS,
    _begin_solver_cooldown_if_needed,
    _node_solver_cooldown_can_resume,
    _record_slider_attempt_started,
    _reset_fallback_state,
    _slider_retry_due,
    _solver_cooldown_active,
    _sync_challenge_state,
)
from tools.pc2_solver_scope import (
    check_cdp_healthy,
    compact_active_challenge_pages,
    notify_manual_challenge,
)
from tools.pc2_solver_scope_policy import (
    manual_challenge_registration_needed,
    node_solver_execution_block_reason,
    select_solver_scope_status,
    solver_request_target_urls,
    solver_status_requires_manual_only,
)
from tools.pc2_solver_state_store import _load_fallback_state, _save_fallback_state
from tools.pc2_solver_transport import (
    log_event,
    read_solver_status,
    write_solver_heartbeat,
)


def local_solver_loop(
    api_base_url: str | None = None,
    cdp_endpoint: str | None = None,
    poll_seconds: float | None = None,
    max_attempts: int | None = None,
    expected_node_id: str | None = None,
) -> None:
    if api_base_url is None:
        api_base_url = DEFAULT_API_BASE_URL
    if cdp_endpoint is None:
        cdp_endpoint = DEFAULT_CDP_ENDPOINT
    if poll_seconds is None:
        poll_seconds = DEFAULT_POLL_SECONDS
    if max_attempts is None:
        max_attempts = DEFAULT_MAX_ATTEMPTS
    prepare_solver_browser(
        api_base_url, cdp_endpoint, poll_seconds, max_attempts, expected_node_id
    )
    last_probe_target = None
    last_auth_confirmed_at = 0.0
    probe_counter = 0
    while True:
        write_solver_heartbeat("polling")
        try:
            pending_control = process_pending_control_actions(
                api_base_url=api_base_url,
                cdp_endpoint=cdp_endpoint,
                expected_node_id=expected_node_id,
                poll_seconds=poll_seconds,
                last_probe_target=last_probe_target,
                last_auth_confirmed_at=last_auth_confirmed_at,
            )
            last_probe_target = pending_control["last_probe_target"]
            last_auth_confirmed_at = pending_control["last_auth_confirmed_at"]
            if pending_control.get("reset_probe_counter"):
                probe_counter = 0
            if pending_control["handled"]:
                continue
            solver_status = read_solver_status(api_base_url)
            if "error" in solver_status:
                log_event({"kind": "status_error", "error": solver_status["error"]})
                time.sleep(poll_seconds)
                continue
            compaction = compact_active_challenge_pages(cdp_endpoint, solver_status)
            if compaction.get("closed"):
                log_event(
                    {
                        "kind": "scoped_challenge_tabs_compacted",
                        "closed": compaction.get("closed"),
                        "scopes": compaction.get("scopes"),
                    }
                )
            solver_status = reset_forced_solver_scopes(
                api_base_url,
                cdp_endpoint,
                solver_status,
                expected_node_id,
            )
            fallback_state = _load_fallback_state()
            solver_status = select_solver_scope_status(
                solver_status,
                preferred_challenge_id=fallback_state.get("challenge_id"),
            )
            paused = bool(solver_status.get("paused"))
            running = bool(solver_status.get("running"))
            manual_required = bool(solver_status.get("manual_required"))
            if (
                solver_status_requires_manual_only(solver_status)
                and not manual_challenge_registration_needed(solver_status)
                and not _node_solver_cooldown_can_resume(fallback_state, solver_status)
            ):
                if fallback_state.get("terminal_manual_pending"):
                    fallback_state["terminal_manual_pending"] = False
                    fallback_state["manual_pushed"] = True
                    _save_fallback_state(fallback_state)
                log_event(
                    {
                        "kind": "waiting_for_manual_auth",
                        "challenge_id": solver_status.get("challenge_id"),
                    }
                )
                time.sleep(poll_seconds)
                continue
            # Manual escalation is opt-in. A stale fallback latch must never disable
            # the automatic solver after an operator turns manual fallback off.
            fallback_state, challenge_reset = _sync_challenge_state(
                fallback_state,
                solver_status.get("challenge_id"),
                scope=solver_status.get("scope"),
            )
            if challenge_reset:
                last_probe_target = None
                log_event(
                    {
                        "kind": "slider_challenge_changed",
                        "challenge_id": fallback_state.get("challenge_id"),
                    }
                )
            if retry_terminal_manual_report(
                fallback_state,
                solver_status,
                partial(
                    notify_manual_challenge,
                    api_base_url,
                    solver_status,
                    expected_node_id,
                ),
                _save_fallback_state,
            ):
                time.sleep(poll_seconds)
                continue
            cooldown_started = _begin_solver_cooldown_if_needed(fallback_state)
            if cooldown_started:
                _save_fallback_state(fallback_state)
                log_event(
                    {
                        "kind": "solver_cooldown_started",
                        "until": fallback_state["solver_cooldown_until"],
                        "seconds": max(0.0, SOLVER_COOLDOWN_SECONDS),
                        "consecutive_failures": fallback_state.get(
                            "consecutive_failures", 0
                        ),
                    }
                )
            blocked_report = _retry_node_solver_blocked_report(
                api_base_url,
                solver_status,
                fallback_state,
                expected_node_id=expected_node_id,
            )
            if blocked_report.get("attempted"):
                log_event(
                    {
                        "kind": "node_solver_blocked_report",
                        "confirmed": blocked_report.get("confirmed"),
                        "attempt": fallback_state.get(
                            "node_solver_blocked_report_attempts", 0
                        ),
                        "result_status": (blocked_report.get("result") or {}).get(
                            "status"
                        ),
                        "error": (blocked_report.get("result") or {}).get("error"),
                    }
                )
            if _solver_cooldown_active(fallback_state):
                _save_fallback_state(fallback_state)
                log_event(
                    {
                        "kind": "solver_cooldown_active",
                        "until": fallback_state.get("solver_cooldown_until"),
                        "reason": fallback_state.get("solver_cooldown_reason"),
                        "consecutive_failures": fallback_state.get(
                            "consecutive_failures", 0
                        ),
                    }
                )
                time.sleep(poll_seconds)
                continue
            cooldown_until = float(fallback_state.get("solver_cooldown_until") or 0)
            if cooldown_until and cooldown_until <= time.time():
                fallback_state = _mark_collection_resume_pending(fallback_state)
                log_event(
                    {
                        "kind": "solver_cooldown_elapsed",
                        "resume_request_id": fallback_state.get(
                            "collection_resume_request_id"
                        ),
                    }
                )
                resume_result = _retry_pending_collection_resume(
                    api_base_url,
                    state=fallback_state,
                )
                if resume_result.get("confirmed"):
                    cleanup_target = resolve_stale_challenge_probe_target_after_resume(
                        cdp_endpoint,
                        last_probe_target,
                        resume_result,
                    )
                    cleanup = close_stale_challenge_probe_target(
                        cdp_endpoint, cleanup_target
                    )
                    last_probe_target = None
                    last_auth_confirmed_at = time.time()
                    probe_counter = 0
                    log_event(
                        {
                            "kind": "collection_resume_confirmed",
                            "result": resume_result.get("result"),
                            "challenge_target_cleanup": cleanup,
                        }
                    )
                else:
                    log_event(
                        {
                            "kind": "collection_resume_pending",
                            "request_id": fallback_state.get(
                                "collection_resume_request_id"
                            ),
                            "next_retry_at": resume_result.get("next_retry_at"),
                            "result": resume_result.get("result"),
                        }
                    )
                time.sleep(poll_seconds)
                continue
            if fallback_state.get("manual_pushed"):
                if not manual_required:
                    # PC1 manual auth completed/cleared; reset fallback state
                    log_event({"kind": "fallback_manual_resolved"})
                    _reset_fallback_state()
                elif _manual_fallback_latch_active(fallback_state, manual_required):
                    log_event(
                        {
                            "kind": "fallback_waiting_manual_auth",
                            "manual_required": manual_required,
                        }
                    )
                    time.sleep(poll_seconds)
                    continue
                else:
                    log_event(
                        {
                            "kind": "fallback_manual_latch_bypassed",
                            "manual_required": manual_required,
                        }
                    )
                    _reset_fallback_state()
            # Primary trigger: API says paused + not running (standard flow)
            api_trigger = paused and not running
            last_request = solver_status.get("last_request")
            requested_target_urls = solver_request_target_urls(last_request)
            # Secondary trigger: probe CDP for slider whenever manual_required is set.
            # The Docker solver keeps resetting the API state via manual_retry, so we check CDP directly.
            cdp_trigger = False
            probe_target = None
            probe_request_target_url = ""
            if manual_required or api_trigger:
                probe_target, probe_request_target_url = probe_requested_targets(
                    cdp_endpoint,
                    requested_target_urls,
                    periodic=False,
                    running=running,
                    paused=paused,
                )
                cdp_trigger = bool(probe_target)
                last_probe_target = probe_target

            if api_trigger and not cdp_trigger:
                recovery = recover_stale_pause(
                    api_base_url,
                    cdp_endpoint,
                    solver_status,
                    requested_target_urls,
                    expected_node_id,
                    last_auth_confirmed_at,
                )
                last_probe_target = recovery["last_probe_target"]
                last_auth_confirmed_at = recovery["last_auth_confirmed_at"]
                if recovery["reset_probe_counter"]:
                    probe_counter = 0
                time.sleep(poll_seconds)
                continue
            # Periodic CDP probe even when API says not paused, to catch slider after Docker resets state
            probe_counter += 1
            # Probe every ~30 seconds. The previous calculation multiplied the
            # poll duration by three and then treated that value as an iteration
            # count, turning a 30-second probe into a 5-minute probe at the
            # default 10-second polling interval.
            _probe_interval = max(1, int(30 / max(1, poll_seconds)))
            post_auth_probe_grace = _post_auth_cdp_probe_grace_active(
                last_auth_confirmed_at
            )
            if (
                not api_trigger
                and not cdp_trigger
                and not manual_required
                and not post_auth_probe_grace
                and probe_counter >= _probe_interval
            ):
                probe_counter = 0
                probe_target, probe_request_target_url = probe_requested_targets(
                    cdp_endpoint, requested_target_urls, periodic=True
                )
                cdp_trigger = bool(probe_target)
                if cdp_trigger:
                    last_probe_target = probe_target
            if not cdp_trigger:
                time.sleep(poll_seconds)
                continue
            # CDP probing can take several seconds. Re-read the control plane at
            # the execution boundary so a concurrently started NAS solver wins
            # instead of both processes acting on the same browser challenge.
            latest_solver_status = select_solver_scope_status(
                read_solver_status(api_base_url),
                preferred_challenge_id=solver_status.get("challenge_id"),
            )
            execution_block_reason = node_solver_execution_block_reason(
                latest_solver_status,
                cdp_endpoint,
                expected_node_id,
            )
            if execution_block_reason:
                if (
                    execution_block_reason == "manual_only"
                    and manual_challenge_registration_needed(latest_solver_status)
                ):
                    manual_report = notify_manual_challenge(
                        api_base_url,
                        latest_solver_status,
                        expected_node_id,
                    )
                    report_solver = manual_report.get("captcha_solver")
                    log_event(
                        {
                            "kind": "manual_challenge_reported",
                            "status": manual_report.get("status"),
                            "ok": manual_report.get("ok"),
                            "error": manual_report.get("error"),
                            "challenge_id": report_solver.get("challenge_id")
                            if isinstance(report_solver, dict)
                            else None,
                        }
                    )
                log_event(
                    {
                        "kind": "local_solver_execution_blocked",
                        "reason": execution_block_reason,
                    }
                )
                time.sleep(poll_seconds)
                continue
            solver_status = latest_solver_status
            last_request = solver_status.get("last_request")
            target_url = match_solver_request_target_url(
                last_request,
                probe_request_target_url,
                cdp_endpoint,
            )
            if not target_url:
                log_event(
                    {
                        "kind": "skip_probe_target_superseded",
                        "selected_target_url": probe_request_target_url,
                    }
                )
                time.sleep(poll_seconds)
                continue
            if not check_cdp_healthy(cdp_endpoint):
                log_event(
                    {"kind": "cdp_unhealthy_before_solve", "cdp_endpoint": cdp_endpoint}
                )
                time.sleep(poll_seconds)
                continue
            fallback_state = _load_fallback_state()
            if not _slider_retry_due(fallback_state):
                log_event(
                    {
                        "kind": "slider_retry_wait",
                        "next_attempt_at": fallback_state.get("slider_next_attempt_at"),
                        "attempts": fallback_state.get("slider_attempts", 0),
                    }
                )
                time.sleep(poll_seconds)
                continue
            scheduled_attempt = int(fallback_state.get("slider_attempts", 0) or 0) + 1
            drag_profile_offset = (scheduled_attempt - 1) % max(
                DEFAULT_DRAG_PROFILE_VARIANTS, 1
            )
            log_event(
                {
                    "kind": "slider_attempt_started",
                    "attempt": scheduled_attempt,
                    "max_attempts": max(1, SOLVER_COOLDOWN_FAIL_THRESHOLD),
                    "drag_profile_offset": drag_profile_offset,
                }
            )
            _record_slider_attempt_started(fallback_state)
            write_solver_heartbeat(
                "solver_attempt",
                challenge_id=fallback_state.get("challenge_id"),
                attempt=scheduled_attempt,
            )
            success = attempt_or_manual_handoff(
                partial(
                    run_solver_local_with_deadline,
                    cdp_endpoint,
                    target_url,
                    max_attempts=max_attempts,
                    probe_target=probe_target,
                    drag_profile_offset=drag_profile_offset,
                ),
                fallback_state,
                solver_status,
                partial(
                    notify_manual_challenge,
                    api_base_url,
                    solver_status,
                    expected_node_id,
                ),
                _save_fallback_state,
            )
            if success is None:
                write_solver_heartbeat("waiting_for_manual_auth")
                log_event(
                    {
                        "kind": "terminal_manual_handoff",
                        "scope": solver_status.get("scope"),
                    }
                )
                time.sleep(poll_seconds)
                continue
            write_solver_heartbeat("polling")
            if success:
                confirmation = confirm_local_solver_success(
                    api_base_url,
                    solver_status,
                    target_url,
                    cdp_endpoint,
                    expected_node_id,
                )
                if confirmation.get("confirmed"):
                    last_auth_confirmed_at = time.time()
                    probe_counter = 0
            else:
                last_probe_target = record_failed_attempt(
                    api_base_url, cdp_endpoint, target_url, probe_target
                )
        except Exception as exc:  # noqa: BLE001 -- daemon reports a failed poll and retries
            log_event(
                {
                    "kind": "loop_error",
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                }
            )
        time.sleep(poll_seconds)


__all__ = ("local_solver_loop",)
