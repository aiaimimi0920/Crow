from __future__ import annotations

import json
import time
import uuid
from typing import cast

from src.project_environment import getenv as project_getenv
from tools.pc2_solver_auth import (
    _auth_complete_response_confirmed,
    notify_auth_complete,
)
from tools.pc2_solver_config import AUTH_COMPLETE_PENDING_MAX_SECONDS
from tools.pc2_solver_retry_state import (
    _auth_complete_retry_delay,
    _reset_fallback_state,
)
from tools.pc2_solver_scope_policy import (
    _challenge_scope_for_url,
    node_owns_last_request,
    select_solver_scope_status,
    solver_status_requires_manual_only,
)
from tools.pc2_solver_state_store import _load_fallback_state, _save_fallback_state
from tools.pc2_solver_transport import log_event, read_solver_status


def _new_auth_completion_id() -> str:
    node_id = project_getenv("CROW_NODE_ID", "pc2").strip() or "pc2"
    return f"{node_id}-{int(time.time() * 1000)}-{uuid.uuid4().hex}"


def _mark_auth_complete_pending(
    target_url: object, challenge_id: object = None
) -> dict[str, object]:
    state: dict[str, object] = _load_fallback_state()
    state.update(
        {
            "last_success_at": time.time(),
            "manual_pushed": False,
            "auth_complete_pending": True,
            "auth_completion_id": _new_auth_completion_id(),
            "auth_complete_attempts": 0,
            "auth_complete_next_retry_at": time.time(),
            "auth_complete_last_error": None,
            "auth_complete_target_url": str(target_url or "").strip() or None,
            "scope": _challenge_scope_for_url(target_url),
            "collection_resume_pending": False,
            "collection_resume_request_id": None,
            "collection_resume_attempts": 0,
            "collection_resume_next_retry_at": None,
            "collection_resume_last_error": None,
        }
    )
    resolved_challenge_id = str(challenge_id or "").strip()
    if resolved_challenge_id:
        state["challenge_id"] = resolved_challenge_id
    _save_fallback_state(state)
    return state


def _completion_challenge_id(
    solver_status: dict[str, object],
    latest_solver_status: object,
    target_url: object,
    local_cdp_endpoint: str,
    expected_node_id: str | None = None,
) -> str | None:
    """Accept a rotated challenge id only for the same owned solver request."""
    original_id = str(solver_status.get("challenge_id") or "").strip() or None
    if not isinstance(latest_solver_status, dict) or latest_solver_status.get("error"):
        return original_id
    if solver_status_requires_manual_only(latest_solver_status):
        return original_id
    if not node_owns_last_request(
        latest_solver_status, local_cdp_endpoint, expected_node_id
    ):
        return original_id
    latest_request = latest_solver_status.get("last_request")
    if not isinstance(latest_request, dict):
        return original_id
    latest_target = str(
        latest_request.get("target_url") or latest_request.get("url") or ""
    ).strip()
    if latest_target != str(target_url or "").strip():
        return original_id
    return str(latest_solver_status.get("challenge_id") or "").strip() or original_id


def _clear_expired_auth_confirmation(state: dict[str, object]) -> dict[str, object]:
    cleared = dict(state)
    cleared.update(
        {
            "last_success_at": None,
            "auth_complete_pending": False,
            "auth_completion_id": None,
            "auth_complete_attempts": 0,
            "auth_complete_next_retry_at": None,
            "auth_complete_last_error": None,
            "auth_complete_target_url": None,
        }
    )
    _save_fallback_state(cleared)
    return cleared


def _retry_pending_auth_confirmation(
    api_base_url: str, state: dict[str, object] | None = None, now: float | None = None
) -> dict[str, object]:
    state = dict(state) if isinstance(state, dict) else _load_fallback_state()
    if not state.get("auth_complete_pending"):
        return {
            "pending": False,
            "attempted": False,
            "confirmed": False,
            "state": state,
        }
    current_time = time.time() if now is None else float(now)
    pending_started_at = float(cast("str | float", state.get("last_success_at") or 0))
    pending_age = current_time - pending_started_at if pending_started_at > 0 else 0
    if (
        AUTH_COMPLETE_PENDING_MAX_SECONDS > 0
        and pending_started_at > 0
        and pending_age >= AUTH_COMPLETE_PENDING_MAX_SECONDS
    ):
        latest_solver_status = read_solver_status(api_base_url)
        if (
            isinstance(latest_solver_status, dict)
            and not latest_solver_status.get("error")
            and latest_solver_status.get("manual_required") is True
            and bool(latest_solver_status.get("paused"))
        ):
            cleared_state = _clear_expired_auth_confirmation(state)
            return {
                "pending": False,
                "attempted": False,
                "confirmed": False,
                "superseded": True,
                "reason": "active_challenge_after_auth_confirmation_timeout",
                "pending_age_seconds": pending_age,
                "state": cleared_state,
            }
    next_retry_at = float(
        cast("str | float", state.get("auth_complete_next_retry_at") or 0)
    )
    if next_retry_at > current_time:
        return {
            "pending": True,
            "attempted": False,
            "confirmed": False,
            "next_retry_at": next_retry_at,
            "state": state,
        }

    completion_id = str(state.get("auth_completion_id") or "").strip()
    result = notify_auth_complete(
        api_base_url,
        source="pc2_local_solver",
        completion_id=completion_id,
        challenge_id=state.get("challenge_id"),
        scope=state.get("scope")
        or _challenge_scope_for_url(state.get("auth_complete_target_url")),
    )
    request_attempts = max(1, int(result.get("request_attempts", 1) or 1))
    total_attempts = (
        int(cast("str | int", state.get("auth_complete_attempts", 0) or 0))
        + request_attempts
    )
    if result.get("stale_challenge") is True:
        reset_state = _reset_fallback_state()
        return {
            "pending": False,
            "attempted": True,
            "confirmed": False,
            "superseded": True,
            "result": result,
            "state": reset_state,
        }
    if _auth_complete_response_confirmed(result, completion_id):
        reset_state = _reset_fallback_state()
        return {
            "pending": False,
            "attempted": True,
            "confirmed": True,
            "result": result,
            "state": reset_state,
        }

    error = str(result.get("error") or "").strip()
    if not error:
        try:
            error = json.dumps(result, ensure_ascii=False, sort_keys=True)
        except Exception:  # noqa: BLE001 -- preserve fallback for unencodable server responses
            error = "NAS did not explicitly confirm cleared auth state"
    retry_delay = _auth_complete_retry_delay(total_attempts)
    state.update(
        {
            "auth_complete_pending": True,
            "auth_complete_attempts": total_attempts,
            "auth_complete_next_retry_at": current_time + retry_delay,
            "auth_complete_last_error": error[:1000],
        }
    )
    _save_fallback_state(state)
    return {
        "pending": True,
        "attempted": True,
        "confirmed": False,
        "next_retry_at": state["auth_complete_next_retry_at"],
        "result": result,
        "state": state,
    }


def confirm_local_solver_success(
    api_base_url: str,
    solver_status: dict[str, object],
    target_url: str,
    cdp_endpoint: str,
    expected_node_id: str | None,
) -> dict[str, object]:
    log_event({"kind": "local_solver_success"})
    completed_state = _load_fallback_state()
    completed_state["slider_attempt_started_at"] = None
    completed_state["slider_last_progress_at"] = time.time()
    _save_fallback_state(completed_state)
    completion_status = select_solver_scope_status(
        read_solver_status(api_base_url),
        preferred_challenge_id=solver_status.get("challenge_id"),
    )
    completion_challenge_id = _completion_challenge_id(
        solver_status,
        completion_status,
        target_url,
        cdp_endpoint,
        expected_node_id,
    )
    log_event(
        {
            "kind": "auth_completion_challenge_resolved",
            "started_challenge_id": solver_status.get("challenge_id"),
            "completion_challenge_id": completion_challenge_id,
        }
    )
    pending_state = _mark_auth_complete_pending(
        target_url, challenge_id=completion_challenge_id
    )
    confirmation = _retry_pending_auth_confirmation(api_base_url, state=pending_state)
    log_event({"kind": "auth_complete_result", "result": confirmation})
    return confirmation


__all__ = (
    "_auth_complete_retry_delay",
    "_clear_expired_auth_confirmation",
    "_completion_challenge_id",
    "_mark_auth_complete_pending",
    "_new_auth_completion_id",
    "_retry_pending_auth_confirmation",
    "confirm_local_solver_success",
)
