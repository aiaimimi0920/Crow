from __future__ import annotations

import multiprocessing
import traceback
from multiprocessing.connection import Connection
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from tools.internal_api_http import fetch_json
from tools.pc2_solver_cdp import check_cdp_browser_for_challenge_page
from tools.pc2_solver_config import (
    SOLVER_EXECUTION_TIMEOUT_SECONDS,
    SOLVER_TERMINATE_GRACE_SECONDS,
)
from tools.pc2_solver_diagnostics import solver_attempt_diagnostics
from tools.pc2_solver_manual_handoff import ManualChallengeRequired
from tools.pc2_solver_scope_policy import (
    _challenge_scope_for_url,
    canonical_manual_challenge_target,
    solver_request_target_urls,
)
from tools.pc2_solver_transport import log_event


class ExecutionSolver(Protocol):
    last_failure_reason: str | None

    def __init__(self, *, cdp_endpoint: str, target_url: str) -> None: ...

    def _remember_target_tab(self, tab: dict[str, object]) -> None: ...

    def solve(
        self,
        *,
        max_attempts: int,
        nc_retry_replay_limit: int,
        slider_find_max_retries: int,
        drag_profile_offset: int,
    ) -> bool: ...

    @staticmethod
    def _is_manual_challenge_url(value: object) -> bool: ...

    @staticmethod
    def _is_login_url(value: object) -> bool: ...

    def _open_keepalive_tab(self) -> str | None: ...

    def _close_cdp_target(self, target_id: str) -> bool: ...

    def _solver_target_scope(self, value: object) -> str: ...

    def _is_challenge_tab(self, tab: dict[str, object]) -> bool: ...

    def _open_target_tab(self) -> dict[str, object] | None: ...

    def _solver_target_route(self, value: object) -> str: ...


def _solver_class() -> type[ExecutionSolver]:
    from src.captcha_solver import CaptchaSolver

    return cast(type[ExecutionSolver], CaptchaSolver)


def run_solver_local(
    cdp_endpoint: str,
    target_url: str,
    max_attempts: int = 50,
    probe_target: dict[str, object] | None = None,
    drag_profile_offset: int = 0,
) -> bool:
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
        log_event(
            {
                "kind": "local_solver_error",
                "error": repr(exc),
                "traceback": traceback.format_exc(),
            }
        )
        return False


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
        with solver_attempt_diagnostics():
            success = run_solver_local(
                cdp_endpoint,
                target_url,
                max_attempts=max_attempts,
                probe_target=probe_target,
                drag_profile_offset=drag_profile_offset,
            )
        result = {"success": bool(success)}
    except ManualChallengeRequired:
        result = {"success": False, "failure_reason": "manual_required"}
    except BaseException as exc:  # noqa: BLE001 -- child exit must publish failure and close its pipe
        result = {"success": False, "error": repr(exc)}
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
) -> bool:
    execution_timeout = (
        SOLVER_EXECUTION_TIMEOUT_SECONDS
        if timeout_seconds is None
        else float(timeout_seconds)
    )
    if execution_timeout <= 0:
        return run_solver_local(
            cdp_endpoint,
            target_url,
            max_attempts=max_attempts,
            probe_target=probe_target,
            drag_profile_offset=drag_profile_offset,
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

    Aliyun NC keeps a rejected widget/token in a terminal error state. Clicking
    that same widget repeatedly only replays the stale challenge. Keep the
    scope pause in place, close every non-login challenge page for that scope,
    and open exactly one canonical collection URL for the next scheduled solve.
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
    opened = opener._open_target_tab()
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
    cdp_endpoint: str, target_url: str
) -> dict[str, object]:
    """Recreate one solver-owned collection target after a browser restart."""
    canonical_target = canonical_manual_challenge_target(target_url)
    scope = _challenge_scope_for_url(canonical_target)
    if scope not in {"seed", "detail"}:
        return {
            "attempted": False,
            "opened": False,
            "scope": scope,
            "reason": "invalid_collection_target",
        }

    opener = _solver_class()(cdp_endpoint=cdp_endpoint, target_url=canonical_target)
    requested_route = opener._solver_target_route(canonical_target)
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
    except Exception as exc:  # noqa: BLE001 -- retain structured CDP failure result
        return {
            "attempted": True,
            "opened": False,
            "scope": scope,
            "reason": "cdp_target_list_unavailable",
            "error_type": type(exc).__name__,
        }

    # A newly opened identity-first target can be between Page.navigate and the
    # final challenge/authenticated state. Treat that route as the singleton so
    # the five-second poll cannot create duplicate tabs while it is loading.
    for tab in tabs if isinstance(tabs, list) else []:
        if not isinstance(tab, dict) or tab.get("type") != "page":
            continue
        tab_url = str(tab.get("url") or "").strip()
        if not tab_url or _solver_class()._is_login_url(tab_url):
            continue
        if requested_route and opener._solver_target_route(tab_url) == requested_route:
            return {
                "attempted": False,
                "opened": False,
                "scope": scope,
                "reason": "request_target_already_present",
                "probe_target": {
                    "_target_id": str(tab.get("id") or "").strip(),
                    "_target_url": tab_url,
                    "_target_ws_url": str(
                        tab.get("webSocketDebuggerUrl") or ""
                    ).strip(),
                },
            }

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
    opened = opener._open_target_tab()
    if not isinstance(opened, dict):
        return {
            "attempted": True,
            "opened": False,
            "scope": scope,
            "reason": "missing_target_open_failed",
        }
    return {
        "attempted": True,
        "opened": True,
        "scope": scope,
        "reason": "missing_challenge_target_rebuilt",
        "probe_target": {
            "_target_id": str(opened.get("id") or "").strip(),
            "_target_url": str(opened.get("url") or fresh_target).strip(),
            "_target_ws_url": str(opened.get("webSocketDebuggerUrl") or "").strip(),
        },
    }


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
