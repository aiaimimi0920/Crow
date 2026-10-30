from __future__ import annotations

import multiprocessing
import traceback
from multiprocessing.connection import Connection
from typing import cast
from urllib.parse import urlsplit, urlunsplit

from tools.internal_api_http import fetch_json
from tools.pc2_solver_attempt_policy import (
    preserve_unconfirmed_target,
    safe_failure_reason,
)
from tools.pc2_solver_cdp import check_cdp_browser_for_challenge_page
from tools.pc2_solver_config import (
    SOLVER_EXECUTION_TIMEOUT_SECONDS,
    SOLVER_TERMINATE_GRACE_SECONDS,
)
from tools.pc2_solver_diagnostics import solver_attempt_diagnostics
from tools.pc2_solver_factory import solver_class as _solver_class
from tools.pc2_solver_maintenance import (
    MaintenanceNavigationUnconfirmed,
    open_maintenance_target,
    valid_target_directory,
)
from tools.pc2_solver_manual_handoff import ManualChallengeRequired
from tools.pc2_solver_reference_tabs import record_failed_drags
from tools.pc2_solver_scope_policy import (
    _challenge_scope_for_url,
    canonical_manual_challenge_target,
    solver_request_target_urls,
)
from tools.pc2_solver_transport import log_event


def run_solver_local(
    cdp_endpoint: str,
    target_url: str,
    max_attempts: int = 50,
    probe_target: dict[str, object] | None = None,
    drag_profile_offset: int = 0,
    *,
    failure_details: dict[str, object] | None = None,
) -> bool:
    if failure_details is not None:
        failure_details.clear()
    log_event(
        {
            "kind": "local_solver_start",
            "cdp_endpoint": cdp_endpoint,
            "target_url": target_url,
            "max_attempts": 1,
            "drag_profile_offset": drag_profile_offset,
        }
    )
    try:
        solver = _solver_class()(cdp_endpoint=cdp_endpoint, target_url=target_url)
        if isinstance(probe_target, dict):
            solver._remember_target_tab(
                {
                    "id": probe_target.get("_target_id"),
                    "url": probe_target.get("_target_url"),
                    "webSocketDebuggerUrl": probe_target.get("_target_ws_url"),
                }
            )
        success = solver.solve(
            max_attempts=1,
            nc_retry_replay_limit=2,
            slider_find_max_retries=1,
            drag_profile_offset=drag_profile_offset,
        )
        if not success and failure_details is not None:
            failure_details["failure_reason"] = safe_failure_reason(
                solver.last_failure_reason
            )
        log_event(
            {
                "kind": "local_solver_end",
                "success": success,
                "failure_reason": solver.last_failure_reason,
            }
        )
        if not success and solver.last_failure_reason == "manual_required":
            raise ManualChallengeRequired(
                "Official challenge requires human verification"
            )
        return bool(success)
    except ManualChallengeRequired:
        raise
    except Exception as exc:  # noqa: BLE001 -- retain solver failure reporting boundary
        if failure_details is not None:
            failure_details["failure_reason"] = "execution_unavailable"
        log_event(
            {
                "kind": "local_solver_error",
                "error": repr(exc),
                "traceback": traceback.format_exc(),
            }
        )
        return False


def _run_diagnosed_solver(*args, **kwargs):
    failure_details = kwargs.get("failure_details")
    if failure_details is None:
        failure_details = kwargs["failure_details"] = {}
    with solver_attempt_diagnostics() as diagnostics:
        success = run_solver_local(*args, **kwargs)
    if not success:
        if preserve_unconfirmed_target(failure_details.get("failure_reason")):
            record_failed_drags(
                args[0], diagnostics.failed_drag_verifications, allow_open=False
            )
        else:
            record_failed_drags(args[0], diagnostics.failed_drag_verifications)
    else:
        record_failed_drags(args[0], 0)
    return success


def _run_solver_process_entry(
    result_connection: Connection,
    cdp_endpoint: str,
    target_url: str,
    max_attempts: int,
    probe_target: dict[str, object] | None,
    drag_profile_offset: int,
) -> None:
    result: dict[str, object]
    try:
        failure_details: dict[str, object] = {}
        success = _run_diagnosed_solver(
            cdp_endpoint,
            target_url,
            max_attempts=max_attempts,
            probe_target=probe_target,
            drag_profile_offset=drag_profile_offset,
            failure_details=failure_details,
        )
        result = {"success": bool(success)}
        if not success and failure_details.get("failure_reason"):
            result["failure_reason"] = failure_details["failure_reason"]
    except ManualChallengeRequired:
        result = {"success": False, "failure_reason": "manual_required"}
    except BaseException as exc:  # noqa: BLE001 -- child exit must publish failure and close its pipe
        result = {
            "success": False,
            "failure_reason": "execution_unavailable",
            "error": repr(exc),
        }
    finally:
        try:
            result_connection.send(result)
        except (BrokenPipeError, EOFError, OSError):
            pass
        finally:
            result_connection.close()


def run_solver_local_with_deadline(
    cdp_endpoint: str,
    target_url: str,
    max_attempts: int = 50,
    probe_target: dict[str, object] | None = None,
    drag_profile_offset: int = 0,
    timeout_seconds: float | None = None,
    *,
    failure_details: dict[str, object] | None = None,
) -> bool:
    """Keep the bool interface; optionally return allowlisted failure metadata."""
    if failure_details is not None:
        failure_details.clear()
    execution_timeout = (
        SOLVER_EXECUTION_TIMEOUT_SECONDS
        if timeout_seconds is None
        else float(timeout_seconds)
    )
    if execution_timeout <= 0:
        return _run_diagnosed_solver(
            cdp_endpoint,
            target_url,
            max_attempts=max_attempts,
            probe_target=probe_target,
            drag_profile_offset=drag_profile_offset,
            failure_details=failure_details,
        )

    context = multiprocessing.get_context("spawn")
    result_receiver, result_sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_run_solver_process_entry,
        args=(
            result_sender,
            cdp_endpoint,
            target_url,
            max_attempts,
            probe_target,
            drag_profile_offset,
        ),
        name="fapaifang-local-solver-attempt",
    )
    try:
        process.start()
    except Exception as exc:  # noqa: BLE001 -- child startup errors return failure
        result_receiver.close()
        result_sender.close()
        try:
            process.close()
        except ValueError:
            pass
        log_event({"kind": "local_solver_process_start_error", "error": repr(exc)})
        if failure_details is not None:
            failure_details["failure_reason"] = "execution_unavailable"
        return False
    result_sender.close()
    process.join(execution_timeout)

    if process.is_alive():
        process.terminate()
        process.join(max(0.0, SOLVER_TERMINATE_GRACE_SECONDS))
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(max(0.0, SOLVER_TERMINATE_GRACE_SECONDS))
        still_alive = process.is_alive()
        result_receiver.close()
        log_event(
            {
                "kind": "local_solver_execution_timeout",
                "timeout_seconds": execution_timeout,
                "terminated": not still_alive,
            }
        )
        if still_alive:
            raise SystemExit("hung local solver child survived terminate and kill")
        process.close()
        if failure_details is not None:
            failure_details["failure_reason"] = "deadline_exceeded"
        return False

    exit_code = process.exitcode
    try:
        result = result_receiver.recv() if result_receiver.poll() else None
    except (EOFError, OSError) as exc:
        result = {"success": False, "error": repr(exc)}
    finally:
        result_receiver.close()
        process.close()
    if not isinstance(result, dict):
        log_event({"kind": "local_solver_process_no_result", "exit_code": exit_code})
        if failure_details is not None:
            failure_details["failure_reason"] = "execution_unavailable"
        return False
    if result.get("error"):
        log_event(
            {
                "kind": "local_solver_process_error",
                "exit_code": exit_code,
                "error": result["error"],
            }
        )
    if result.get("failure_reason") == "manual_required":
        raise ManualChallengeRequired("Official challenge requires human verification")
    if not result.get("success") and failure_details is not None:
        failure_details["failure_reason"] = safe_failure_reason(
            result.get("failure_reason")
            or ("execution_unavailable" if result.get("error") else None)
        )
    return bool(result.get("success"))


def close_stale_challenge_probe_target(
    cdp_endpoint: str, probe_target: object
) -> dict[str, object]:
    if not isinstance(probe_target, dict):
        return {"attempted": False, "closed": False, "reason": "missing_probe_target"}
    target_id = str(probe_target.get("_target_id") or "").strip()
    target_url = str(probe_target.get("_target_url") or "").strip()
    challenge_evidence = probe_target.get("_challenge_evidence")
    if not target_id:
        return {"attempted": False, "closed": False, "reason": "missing_target_id"}
    if not challenge_evidence and not _solver_class()._is_manual_challenge_url(
        target_url
    ):
        return {"attempted": False, "closed": False, "reason": "target_not_challenge"}

    solver = _solver_class()(cdp_endpoint=cdp_endpoint, target_url=target_url)
    keepalive_target_id = None
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        for tab in tabs if isinstance(tabs, list) else []:
            if (
                isinstance(tab, dict)
                and tab.get("type") == "page"
                and str(tab.get("url") or "").strip().lower() == "about:blank"
                and str(tab.get("id") or "").strip() != target_id
            ):
                keepalive_target_id = str(tab.get("id") or "").strip()
                break
    except Exception:  # noqa: BLE001 -- retain keepalive creation fallback
        keepalive_target_id = None
    keepalive_reused = bool(keepalive_target_id)
    if not keepalive_target_id:
        keepalive_target_id = solver._open_keepalive_tab()
    closed = solver._close_cdp_target(target_id)
    if not closed and keepalive_target_id and not keepalive_reused:
        solver._close_cdp_target(keepalive_target_id)
    return {
        "attempted": True,
        "closed": bool(closed),
        "target_id": target_id,
        "keepalive_opened": bool(keepalive_target_id and not keepalive_reused),
        "keepalive_reused": keepalive_reused,
    }


def rotate_failed_challenge_target(
    cdp_endpoint: str, target_url: str, probe_target: dict[str, object] | None = None
) -> dict[str, object]:
    """Replace rejected challenge tabs with one fresh canonical request.

    Keep the scope pause in place, close only non-login challenge pages bound
    to this canonical request, and open one target for the next scheduled solve.
    Another worker's same-scope page is not a duplicate of the failed request.
    """
    canonical_target = canonical_manual_challenge_target(target_url)
    scope = _challenge_scope_for_url(canonical_target)
    if scope not in {"seed", "detail"}:
        return {
            "attempted": False,
            "opened": False,
            "closed": 0,
            "reason": "invalid_collection_target",
        }

    probe_url = str((probe_target or {}).get("_target_url") or "").strip()
    if probe_url and _solver_class()._is_login_url(probe_url):
        return {
            "attempted": False,
            "opened": False,
            "closed": 0,
            "scope": scope,
            "reason": "login_window_preserved",
        }

    closer = _solver_class()(cdp_endpoint=cdp_endpoint, target_url=canonical_target)
    closed = 0
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        if not valid_target_directory(tabs):
            raise TypeError("Invalid CDP target directory")
    except Exception as exc:  # noqa: BLE001 -- retain structured CDP failure result
        return {
            "attempted": True,
            "opened": False,
            "closed": 0,
            "scope": scope,
            "reason": "cdp_target_list_unavailable",
            "error_type": type(exc).__name__,
        }

    for tab in tabs if isinstance(tabs, list) else []:
        if not isinstance(tab, dict) or tab.get("type") != "page":
            continue
        target_id = str(tab.get("id") or "").strip()
        tab_url = str(tab.get("url") or "").strip()
        if not target_id or _solver_class()._is_login_url(tab_url):
            continue
        if closer._solver_target_scope(tab_url) != scope:
            continue
        if not closer._manual_challenge_matches_requested_target(tab_url):
            continue
        if not closer._is_challenge_tab(tab):
            continue
        if closer._close_cdp_target(target_id):
            closed += 1

    # The internal marker distinguishes this single solver-owned navigation
    # without carrying x5secdata or any other rejected challenge query.
    parsed = urlsplit(canonical_target)
    fresh_target = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "&".join(filter(None, (parsed.query, "__captcha_solver_bg=1"))),
            "",
        )
    )
    opener = _solver_class()(cdp_endpoint=cdp_endpoint, target_url=fresh_target)
    try:
        opened = open_maintenance_target(opener)
    except MaintenanceNavigationUnconfirmed as deferred:
        return deferred.result(scope, closed=closed)
    if not isinstance(opened, dict):
        return {
            "attempted": True,
            "opened": False,
            "closed": closed,
            "scope": scope,
            "reason": "fresh_target_open_failed",
        }
    probe = {
        "_target_id": str(opened.get("id") or "").strip(),
        "_target_url": str(opened.get("url") or fresh_target).strip(),
        "_target_ws_url": str(opened.get("webSocketDebuggerUrl") or "").strip(),
    }
    return {
        "attempted": True,
        "opened": True,
        "closed": closed,
        "scope": scope,
        "reason": "rejected_challenge_replaced",
        "probe_target": probe,
    }


def rebuild_missing_challenge_target(
    cdp_endpoint: str,
    target_url: str,
    *,
    pending_target: dict[str, object] | None = None,
) -> dict[str, object]:
    from tools.pc2_solver_target_recovery import (
        rebuild_missing_challenge_target as rebuild,
    )

    return rebuild(
        cdp_endpoint,
        target_url,
        pending_target=pending_target,
        solver_type=_solver_class(),
        read_json=fetch_json,
        open_target=open_maintenance_target,
    )


def resolve_stale_challenge_probe_target_after_resume(
    cdp_endpoint: str, probe_target: object, resume_result: object
) -> dict[str, object] | None:
    """Recover the exact challenge target after a solver restart during cooldown."""
    if isinstance(probe_target, dict):
        # Failed-target rotation records the canonical collection URL at open
        # time. During cooldown that same target can navigate to the challenge,
        # so refresh its live URL/DOM before the fail-closed cleanup check.
        target_url = str(probe_target.get("_target_url") or "").strip()
        refreshed_target = check_cdp_browser_for_challenge_page(
            cdp_endpoint,
            target_url=target_url or None,
        )
        if refreshed_target:
            return cast("dict[str, object]", refreshed_target)
        return probe_target
    if not isinstance(resume_result, dict):
        return None
    payload = resume_result.get("result")
    if not isinstance(payload, dict):
        return None
    solver_status = payload.get("captcha_solver")
    if not isinstance(solver_status, dict):
        return None
    for target_url in solver_request_target_urls(solver_status.get("last_request")):
        recovered_target = check_cdp_browser_for_challenge_page(
            cdp_endpoint,
            target_url=target_url,
        )
        if recovered_target:
            return cast("dict[str, object]", recovered_target)
    return None


__all__ = (
    "_run_solver_process_entry",
    "close_stale_challenge_probe_target",
    "rebuild_missing_challenge_target",
    "resolve_stale_challenge_probe_target_after_resume",
    "rotate_failed_challenge_target",
    "run_solver_local",
    "run_solver_local_with_deadline",
)
