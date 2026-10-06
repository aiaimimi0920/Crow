from __future__ import annotations

import time
from typing import TypedDict, cast

from src.project_environment import getenv as project_getenv
from tools.pc2_auth_recovery import process_nas_auth_recovery_once
from tools.pc2_solver_auth import _recent_healthy_auth_snapshot
from tools.pc2_solver_auth_pending import (
    _mark_auth_complete_pending,
    _retry_pending_auth_confirmation,
)
from tools.pc2_solver_cdp import check_cdp_browser_for_authenticated_target
from tools.pc2_solver_config import (
    AUTH_RECOVERY_MARKER_PATH,
    AUTH_RECOVERY_SNAPSHOT_PATH,
    AUTH_RECOVERY_TOKEN_PATH,
)
from tools.pc2_solver_execution import (
    close_stale_challenge_probe_target,
    rebuild_missing_challenge_target,
    resolve_stale_challenge_probe_target_after_resume,
)
from tools.pc2_solver_fallback import (
    _retry_node_solver_blocked_report,
    _retry_pending_collection_resume,
)
from tools.pc2_solver_retry_state import _reset_fallback_state
from tools.pc2_solver_scope import close_challenge_pages_for_scope, notify_force_reset
from tools.pc2_solver_scope_policy import (
    _solver_scope_statuses,
    node_owns_last_request,
    solver_request_target_url,
)
from tools.pc2_solver_state_store import _load_fallback_state
from tools.pc2_solver_transport import (
    log_event,
    nas_auth_recovery_client_enabled,
    read_solver_status,
    write_solver_heartbeat,
)


class ControlResult(TypedDict):
    handled: bool
    last_probe_target: dict[str, object] | None
    last_auth_confirmed_at: float
    reset_probe_counter: bool


def retry_blocked_report(
    api_base_url: str,
    solver_status: dict[str, object],
    state: dict[str, object],
    expected_node_id: str | None,
) -> None:
    report = _retry_node_solver_blocked_report(
        api_base_url, solver_status, state, expected_node_id=expected_node_id
    )
    if report.get("attempted"):
        log_event(
            {
                "kind": "node_solver_blocked_report",
                "confirmed": report.get("confirmed"),
                "attempt": state.get("node_solver_blocked_report_attempts", 0),
                "result_status": (report.get("result") or {}).get("status"),
                "error": (report.get("result") or {}).get("error"),
            }
        )


def process_pending_control_actions(
    *,
    api_base_url: str,
    cdp_endpoint: str,
    expected_node_id: str | None,
    poll_seconds: float,
    last_probe_target: dict[str, object] | None,
    last_auth_confirmed_at: float,
) -> ControlResult:
    if nas_auth_recovery_client_enabled():
        auth_recovery = process_nas_auth_recovery_once(
            api_base_url,
            cdp_endpoint,
            expected_node_id or project_getenv("CROW_NODE_ID", "pc2"),
            AUTH_RECOVERY_SNAPSHOT_PATH,
            AUTH_RECOVERY_MARKER_PATH,
            AUTH_RECOVERY_TOKEN_PATH,
        )
        recovery_action = str(auth_recovery.get("action") or "")
        if recovery_action not in {
            "idle",
            "ignored",
            "waiting_for_collection_progress",
        }:
            log_event({"kind": "nas_auth_recovery", **auth_recovery})
        if recovery_action == "restart_requested":
            write_solver_heartbeat(
                "auth_recovery_restart",
                recovery_id=auth_recovery.get("recovery_id"),
            )
            raise SystemExit(75)

    pending_confirmation = _retry_pending_auth_confirmation(api_base_url)
    if pending_confirmation.get("confirmed"):
        last_auth_confirmed_at = time.time()
        log_event(
            {
                "kind": "auth_complete_confirmed",
                "result": pending_confirmation.get("result"),
            }
        )
        time.sleep(0)
        return {
            "handled": True,
            "reset_probe_counter": True,
            "last_probe_target": last_probe_target,
            "last_auth_confirmed_at": last_auth_confirmed_at,
        }
    if pending_confirmation.get("pending"):
        if pending_confirmation.get("attempted"):
            log_event(
                {
                    "kind": "auth_complete_retry_pending",
                    "next_retry_at": pending_confirmation.get("next_retry_at"),
                    "result": pending_confirmation.get("result"),
                }
            )
        time.sleep(poll_seconds)
        return {
            "handled": True,
            "reset_probe_counter": False,
            "last_probe_target": last_probe_target,
            "last_auth_confirmed_at": last_auth_confirmed_at,
        }

    pending_resume = _retry_pending_collection_resume(api_base_url)
    if pending_resume.get("confirmed"):
        cleanup_target = resolve_stale_challenge_probe_target_after_resume(
            cdp_endpoint,
            last_probe_target,
            pending_resume,
        )
        cleanup = close_stale_challenge_probe_target(cdp_endpoint, cleanup_target)
        last_probe_target = None
        last_auth_confirmed_at = time.time()
        log_event(
            {
                "kind": "collection_resume_confirmed",
                "result": pending_resume.get("result"),
                "challenge_target_cleanup": cleanup,
            }
        )
        time.sleep(0)
        return {
            "handled": True,
            "reset_probe_counter": True,
            "last_probe_target": last_probe_target,
            "last_auth_confirmed_at": last_auth_confirmed_at,
        }
    if pending_resume.get("pending"):
        if pending_resume.get("attempted"):
            log_event(
                {
                    "kind": "collection_resume_pending",
                    "request_id": pending_resume.get("state", {}).get(
                        "collection_resume_request_id"
                    ),
                    "next_retry_at": pending_resume.get("next_retry_at"),
                    "result": pending_resume.get("result"),
                }
            )
        time.sleep(poll_seconds)
        return {
            "handled": True,
            "reset_probe_counter": False,
            "last_probe_target": last_probe_target,
            "last_auth_confirmed_at": last_auth_confirmed_at,
        }
    return {
        "handled": False,
        "reset_probe_counter": False,
        "last_probe_target": last_probe_target,
        "last_auth_confirmed_at": last_auth_confirmed_at,
    }


def _fallback_matches_scope_challenge(
    fallback: dict[str, object], scope: object, challenge_id: object
) -> bool:
    return bool(
        scope in {"seed", "detail"}
        and fallback.get("scope") == scope
        and fallback.get("challenge_id")
        and fallback.get("challenge_id") == challenge_id
    )


def reset_forced_solver_scopes(
    api_base_url: str,
    cdp_endpoint: str,
    solver_status: dict[str, object],
    expected_node_id: str | None,
) -> dict[str, object]:
    force_reset_done = False
    for scope, scoped_status in _solver_scope_statuses(solver_status).items():
        if not isinstance(scoped_status, dict) or not scoped_status.get(
            "force_reset_required"
        ):
            continue
        scoped_request = scoped_status.get("last_request")
        if isinstance(scoped_request, dict) and not node_owns_last_request(
            {"last_request": scoped_request, "running": True},
            cdp_endpoint,
            expected_node_id,
        ):
            continue
        fallback = _load_fallback_state()
        if (
            _fallback_matches_scope_challenge(
                fallback, scope, scoped_status.get("challenge_id")
            )
            and fallback.get("solver_cooldown_until")
            and fallback.get("solver_cooldown_reason") == "repeated_solver_failures"
        ):
            # An expired deadline must reach the resume acknowledgement path first.
            log_event(
                {
                    "kind": "scoped_challenge_force_reset_deferred",
                    "scope": scope,
                    "challenge_id": scoped_status.get("challenge_id"),
                    "cooldown_until": fallback.get("solver_cooldown_until"),
                    "reason": "solver_cooldown_or_resume_pending",
                }
            )
            continue
        cleanup = close_challenge_pages_for_scope(cdp_endpoint, scope)
        reset_result = notify_force_reset(
            api_base_url,
            scope,
            scoped_status.get("challenge_id"),
        )
        if reset_result.get("force_reset") is True:
            fallback = _load_fallback_state()
            if _fallback_matches_scope_challenge(
                fallback, scope, scoped_status.get("challenge_id")
            ):
                _reset_fallback_state(preserve_budget_from=fallback)
        log_event(
            {
                "kind": "scoped_challenge_force_reset",
                "scope": scope,
                "challenge_id": scoped_status.get("challenge_id"),
                "reset": reset_result,
                "cleanup": cleanup,
            }
        )
        force_reset_done = force_reset_done or bool(reset_result.get("force_reset"))
    return (
        cast("dict[str, object]", read_solver_status(api_base_url))
        if force_reset_done
        else solver_status
    )


def recover_stale_pause(
    api_base_url: str,
    cdp_endpoint: str,
    solver_status: dict[str, object],
    requested_target_urls: list[str],
    expected_node_id: str | None,
    last_auth_confirmed_at: float,
) -> ControlResult:
    result: ControlResult = {
        "handled": True,
        "last_probe_target": None,
        "last_auth_confirmed_at": last_auth_confirmed_at,
        "reset_probe_counter": False,
    }
    target_url = solver_request_target_url(solver_status.get("last_request"))
    recent_healthy_snapshot = bool(
        target_url and _recent_healthy_auth_snapshot(solver_status)
    )
    authenticated_target_url = ""
    if not recent_healthy_snapshot:
        for candidate in requested_target_urls:
            authenticated = check_cdp_browser_for_authenticated_target(
                cdp_endpoint, candidate
            )
            if authenticated:
                authenticated_target_url = candidate
                log_event(
                    {
                        "kind": "cdp_authenticated_target_found",
                        "target_id": authenticated.get("_target_id"),
                    }
                )
                break
    confirmation_target = (
        target_url if recent_healthy_snapshot else authenticated_target_url
    )
    if confirmation_target:
        pending = _mark_auth_complete_pending(
            confirmation_target, challenge_id=solver_status.get("challenge_id")
        )
        confirmation = _retry_pending_auth_confirmation(api_base_url, state=pending)
        log_event({"kind": "stale_pause_auth_complete_result", "result": confirmation})
        if confirmation.get("confirmed"):
            result["last_auth_confirmed_at"] = time.time()
            result["reset_probe_counter"] = True
    elif (
        str(solver_status.get("challenge_id") or "").strip()
        and target_url
        and node_owns_last_request(solver_status, cdp_endpoint, expected_node_id)
    ):
        rebuild = rebuild_missing_challenge_target(cdp_endpoint, target_url)
        result["last_probe_target"] = rebuild.get("probe_target")
        result["reset_probe_counter"] = True
        log_event(
            {
                "kind": "missing_challenge_target_rebuild_result",
                "attempted": bool(rebuild.get("attempted")),
                "opened": bool(rebuild.get("opened")),
                "scope": rebuild.get("scope"),
                "reason": rebuild.get("reason"),
                "error_type": rebuild.get("error_type"),
            }
        )
    else:
        log_event(
            {
                "kind": "skip_api_pause_without_cdp_challenge",
                "last_status": solver_status.get("last_status"),
            }
        )
    return result


__all__ = (
    "process_pending_control_actions",
    "recover_stale_pause",
    "reset_forced_solver_scopes",
)
