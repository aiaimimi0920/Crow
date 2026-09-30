from __future__ import annotations

import time
from typing import cast

from src.project_environment import getenv as project_getenv
from tools.internal_api_http import post_json
from tools.pc2_solver_config import (
    AUTH_COMPLETE_REQUEST_ATTEMPTS,
    AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS,
    AUTH_COMPLETE_REQUEST_TIMEOUT_SECONDS,
    POST_AUTH_CDP_PROBE_GRACE_SECONDS,
    RECENT_HEALTHY_AUTH_MAX_AGE_SECONDS,
)
from tools.pc2_solver_transport import _auth_complete_url, _resume_after_cooldown_url


def notify_auth_complete(
    api_base: str,
    source: str = "pc2_local_solver",
    refresh_cookie_snapshot: bool = True,
    completion_id: str | None = None,
    challenge_id: str | None = None,
    scope: str | None = None,
) -> dict[str, object]:
    url = _auth_complete_url(api_base)
    request_payload = {
        "source": source,
        "node_id": project_getenv("CROW_NODE_ID", "pc2").strip() or "pc2",
        "refresh_cookie_snapshot": refresh_cookie_snapshot,
        "completion_id": completion_id,
        "challenge_id": challenge_id,
        "scope": scope,
    }
    report_endpoint = project_getenv("CROW_REPORT_CDP_ENDPOINT", "").strip()
    if report_endpoint:
        request_payload["cdp_endpoint"] = report_endpoint
    attempts = max(1, min(int(AUTH_COMPLETE_REQUEST_ATTEMPTS), 10))
    last_result: dict[str, object] = {
        "ok": False,
        "error": "auth_complete_not_attempted",
    }
    for attempt in range(1, attempts + 1):
        try:
            payload = post_json(
                url,
                request_payload,
                timeout=max(AUTH_COMPLETE_REQUEST_TIMEOUT_SECONDS, 1.0),
            )
            last_result = (
                dict(payload)
                if isinstance(payload, dict)
                else {"ok": False, "raw": payload}
            )
        except Exception as exc:
            last_result = {"ok": False, "error": repr(exc)}
        last_result["request_attempts"] = attempt
        if _auth_complete_response_confirmed(last_result, completion_id):
            return last_result
        if last_result.get("stale_challenge") is True:
            return last_result
        if attempt < attempts and AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS > 0:
            time.sleep(AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS * attempt)
    return last_result


def _response_scope_state(payload: object) -> dict[str, object] | None:
    """Select the scope-local auth state when another scope is still paused.

    The API keeps aggregate ``paused`` fields for old clients.  A list and a
    detail challenge may legitimately overlap, so PC2 must validate the scope
    it just solved instead of waiting for the unrelated scope to clear.
    """
    if not isinstance(payload, dict):
        return None
    solver_status = payload.get("captcha_solver")
    if not isinstance(solver_status, dict):
        return None
    scope = str(payload.get("scope") or "").strip().lower()
    if scope not in {"seed", "detail"}:
        return None
    statuses = solver_status.get("scopes") or solver_status.get("collection_scopes")
    scoped_status = statuses.get(scope) if isinstance(statuses, dict) else None
    if not isinstance(scoped_status, dict):
        scoped_status = {}
    paused = (
        payload.get("scope_paused")
        if "scope_paused" in payload
        else scoped_status.get("paused")
    )
    manual_required = (
        payload.get("scope_manual_required")
        if "scope_manual_required" in payload
        else scoped_status.get("manual_required")
    )
    force_unlock = (
        payload.get("scope_force_unlock_flag_exists")
        if "scope_force_unlock_flag_exists" in payload
        else scoped_status.get("force_unlock_flag_exists", False)
    )
    force_reset = (
        payload.get("scope_force_reset_required")
        if "scope_force_reset_required" in payload
        else scoped_status.get("force_reset_required")
    )
    return {
        "scope": scope,
        "paused": paused,
        "manual_required": manual_required,
        "force_unlock_flag_exists": force_unlock,
        "force_reset_required": force_reset,
    }


def _auth_complete_response_confirmed(
    payload: object, completion_id: str | None
) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("ok") is not True or payload.get("auth_state_confirmed") is not True:
        return False
    if str(payload.get("completion_id") or "") != str(completion_id or ""):
        return False
    solver_status = payload.get("captcha_solver")
    if not isinstance(solver_status, dict):
        return False
    scoped_state = _response_scope_state(payload)
    if scoped_state is not None:
        if scoped_state.get("paused") is not False:
            return False
        manual_required = scoped_state.get("manual_required")
        force_unlock = scoped_state.get("force_unlock_flag_exists")
    else:
        if payload.get("paused") is not False:
            return False
        manual_required = solver_status.get("manual_required")
        force_unlock = solver_status.get("force_unlock_flag_exists")
    return bool(
        manual_required is False
        and force_unlock is False
        and (scoped_state is not None or solver_status.get("paused") is False)
    )


def _recent_healthy_auth_snapshot(
    solver_status: object, now: float | None = None
) -> bool:
    if not isinstance(solver_status, dict):
        return False
    resolved_statuses = {
        "manual_auth_completed",
        "resumed_after_cooldown",
        "resumed",
        "solved",
    }
    if str(solver_status.get("last_status") or "") not in resolved_statuses:
        return False
    if (
        solver_status.get("running") is True
        or solver_status.get("manual_required") is True
        or solver_status.get("force_unlock_flag_exists") is True
    ):
        return False
    snapshot = solver_status.get("cookie_snapshot_refresh")
    if not isinstance(snapshot, dict):
        return False
    result = snapshot.get("result")
    health = result.get("health") if isinstance(result, dict) else None
    if not (
        snapshot.get("status") == "completed"
        and snapshot.get("refreshed") is True
        and isinstance(health, dict)
        and health.get("healthy") is True
    ):
        return False
    try:
        finished_at = float(snapshot.get("last_finished_at_epoch") or 0)
    except (TypeError, ValueError):
        return False
    current_time = time.time() if now is None else float(now)
    age_seconds = current_time - finished_at
    return 0 <= age_seconds <= max(0.0, RECENT_HEALTHY_AUTH_MAX_AGE_SECONDS)


def _post_auth_cdp_probe_grace_active(
    confirmed_at: object, now: float | None = None
) -> bool:
    try:
        completed_at = float(cast("str | float", confirmed_at or 0))
    except (TypeError, ValueError):
        return False
    if completed_at <= 0 or POST_AUTH_CDP_PROBE_GRACE_SECONDS <= 0:
        return False
    current_time = time.time() if now is None else float(now)
    age_seconds = current_time - completed_at
    return 0 <= age_seconds <= POST_AUTH_CDP_PROBE_GRACE_SECONDS


def notify_collection_resume_after_cooldown(
    api_base: str,
    resume_request_id: str,
    challenge_id: str | None = None,
    scope: str | None = None,
) -> dict[str, object]:
    node_id = project_getenv("CROW_NODE_ID", "pc2").strip() or "pc2"
    cdp_endpoint = (
        project_getenv("CROW_REPORT_CDP_ENDPOINT")
        or project_getenv("CROW_CDP_ENDPOINT")
        or ""
    ).strip()
    request_payload = {
        "source": "pc2_local_solver",
        "resume_request_id": resume_request_id,
        "challenge_id": challenge_id,
        "scope": scope,
        "node_id": node_id,
        "cdp_endpoint": cdp_endpoint or None,
    }
    attempts = max(1, min(int(AUTH_COMPLETE_REQUEST_ATTEMPTS), 10))
    last_result: dict[str, object] = {
        "ok": False,
        "error": "resume_after_cooldown_not_attempted",
    }
    for attempt in range(1, attempts + 1):
        try:
            payload = post_json(
                _resume_after_cooldown_url(api_base),
                request_payload,
                timeout=max(AUTH_COMPLETE_REQUEST_TIMEOUT_SECONDS, 1.0),
            )
            last_result = (
                dict(payload)
                if isinstance(payload, dict)
                else {"ok": False, "raw": payload}
            )
        except Exception as exc:
            last_result = {"ok": False, "error": repr(exc)}
        last_result["request_attempts"] = attempt
        if _resume_after_cooldown_response_confirmed(last_result, resume_request_id):
            return last_result
        if last_result.get("stale_challenge") is True:
            return last_result
        if attempt < attempts and AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS > 0:
            time.sleep(AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS * attempt)
    return last_result


def _resume_after_cooldown_response_confirmed(
    payload: object, resume_request_id: str
) -> bool:
    if not isinstance(payload, dict):
        return False
    if (
        payload.get("ok") is not True
        or payload.get("action") != "resume_after_cooldown"
    ):
        return False
    if payload.get("auth_state_confirmed") is not True:
        return False
    if str(payload.get("resume_request_id") or "") != str(resume_request_id or ""):
        return False
    solver_status = payload.get("captcha_solver")
    if not isinstance(solver_status, dict):
        return False
    scoped_state = _response_scope_state(payload)
    if scoped_state is not None:
        if scoped_state.get("paused") is not False:
            return False
        manual_required = scoped_state.get("manual_required")
        force_unlock = scoped_state.get("force_unlock_flag_exists")
    else:
        if payload.get("paused") is not False:
            return False
        manual_required = solver_status.get("manual_required")
        force_unlock = solver_status.get("force_unlock_flag_exists")
    return bool(
        manual_required is False
        and force_unlock is False
        and (scoped_state is not None or solver_status.get("paused") is False)
    )


__all__ = (
    "notify_auth_complete",
    "_response_scope_state",
    "_auth_complete_response_confirmed",
    "_recent_healthy_auth_snapshot",
    "_post_auth_cdp_probe_grace_active",
    "notify_collection_resume_after_cooldown",
    "_resume_after_cooldown_response_confirmed",
)
