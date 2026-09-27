from __future__ import annotations

import json
import os
import time
import uuid
from typing import cast

from tools.internal_api_http import post_json
from tools.pc2_solver_auth import (
    _resume_after_cooldown_response_confirmed,
    notify_collection_resume_after_cooldown,
)
from tools.pc2_solver_retry_state import (
    SLIDER_RETRY_INTERVAL_SECONDS,
    SOLVER_COOLDOWN_FAIL_THRESHOLD,
    SOLVER_COOLDOWN_SECONDS,
    _auth_complete_retry_delay,
    _begin_solver_cooldown_if_needed,
    _node_solver_cooldown_can_resume,
    _record_slider_attempt_failure,
    _record_slider_attempt_started,
    _reset_fallback_state,
    _slider_retry_due,
    _solver_cooldown_active,
    _sync_challenge_state,
)
from tools.pc2_solver_scope import notify_solver_blocked
from tools.pc2_solver_state_store import (
    FALLBACK_STATE_PATH,
    _default_fallback_state,
    _load_fallback_state,
    _save_fallback_state,
)

FALLBACK_FAIL_THRESHOLD = int(
    os.environ.get("FAPAI_SOLVER_FALLBACK_FAIL_THRESHOLD", "10")
)

FALLBACK_STALL_SECONDS = int(
    os.environ.get("FAPAI_SOLVER_FALLBACK_STALL_SECONDS", "600")
)


def manual_fallback_enabled() -> bool:
    """Keep automatic solving primary unless manual escalation is explicitly enabled."""
    value = os.environ.get("FAPAI_SOLVER_MANUAL_FALLBACK_ENABLED", "0")
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _manual_fallback_latch_active(
    fallback_state: dict[str, object], manual_required: object
) -> bool:
    return bool(
        manual_fallback_enabled()
        and manual_required
        and fallback_state.get("manual_pushed")
    )


def _report_manual_captcha(
    api_base_url: str, cdp_endpoint: str, target_url: str | None
) -> dict[str, object]:
    url = api_base_url.rstrip("/") + "/report_manual_captcha"
    payload = {
        "url": target_url or "",
        "cdp_endpoint": cdp_endpoint,
        "node_id": os.environ.get("FAPAI_NODE_ID", "").strip() or None,
        "manual_only": True,
        "timestamp": int(time.time() * 1000),
    }
    try:
        loaded = post_json(url, payload, timeout=10)
        return dict(loaded) if isinstance(loaded, dict) else {"raw": loaded}
    except Exception as exc:  # noqa: BLE001 -- retain the manual-report failure envelope
        return {"error": repr(exc)}


def _retry_node_solver_blocked_report(
    api_base_url: str,
    solver_status: dict[str, object],
    state: dict[str, object],
    expected_node_id: str | None = None,
    now: float | None = None,
) -> dict[str, object]:
    current_time = time.time() if now is None else float(now)
    state_challenge_id = str(state.get("challenge_id") or "").strip()
    status_challenge_id = str(solver_status.get("challenge_id") or "").strip()
    state_scope = str(state.get("scope") or "").strip()
    status_scope = str(solver_status.get("scope") or "").strip()
    if (
        not state_challenge_id
        or state_challenge_id != status_challenge_id
        or (state_scope and status_scope and state_scope != status_scope)
    ):
        return {
            "attempted": False,
            "confirmed": False,
            "reason": "challenge_mismatch",
            "state": state,
        }
    if state.get("solver_cooldown_reason") != "repeated_solver_failures":
        return {"attempted": False, "confirmed": False, "state": state}
    if not state.get("solver_cooldown_until") or state.get(
        "node_solver_blocked_reported"
    ):
        return {
            "attempted": False,
            "confirmed": bool(state.get("node_solver_blocked_reported")),
            "state": state,
        }
    if (
        float(
            cast(
                "str | float",
                state.get("node_solver_blocked_report_next_retry_at") or 0,
            )
        )
        > current_time
    ):
        return {"attempted": False, "confirmed": False, "state": state}

    result = notify_solver_blocked(
        api_base_url,
        solver_status,
        state,
        expected_node_id=expected_node_id,
    )
    state["node_solver_blocked_report_attempts"] = (
        int(cast("str | int", state.get("node_solver_blocked_report_attempts", 0) or 0))
        + 1
    )
    confirmed = result.get("status") == "node_solver_blocked"
    state["node_solver_blocked_reported"] = confirmed
    if confirmed:
        state["node_solver_blocked_report_next_retry_at"] = None
        state["node_solver_blocked_report_last_error"] = None
    else:
        state["node_solver_blocked_report_next_retry_at"] = current_time + max(
            5.0,
            SLIDER_RETRY_INTERVAL_SECONDS,
        )
        state["node_solver_blocked_report_last_error"] = str(
            result.get("error") or result.get("status") or "report_failed"
        )
    _save_fallback_state(state)
    return {
        "attempted": True,
        "confirmed": confirmed,
        "result": result,
        "state": state,
    }


def _new_collection_resume_request_id() -> str:
    node_id = os.environ.get("FAPAI_NODE_ID", "pc2").strip() or "pc2"
    return f"{node_id}-resume-{int(time.time() * 1000)}-{uuid.uuid4().hex}"


def _mark_collection_resume_pending(
    state: dict[str, object] | None = None, now: float | None = None
) -> dict[str, object]:
    current_time = time.time() if now is None else float(now)
    state = dict(state) if isinstance(state, dict) else _load_fallback_state()
    if not state.get("collection_resume_pending"):
        state.update(
            {
                "collection_resume_pending": True,
                "collection_resume_request_id": _new_collection_resume_request_id(),
                "collection_resume_attempts": 0,
                "collection_resume_next_retry_at": current_time,
                "collection_resume_last_error": None,
            }
        )
    _save_fallback_state(state)
    return state


def _retry_pending_collection_resume(
    api_base_url: str, state: dict[str, object] | None = None, now: float | None = None
) -> dict[str, object]:
    state = dict(state) if isinstance(state, dict) else _load_fallback_state()
    if not state.get("collection_resume_pending"):
        return {
            "pending": False,
            "attempted": False,
            "confirmed": False,
            "state": state,
        }
    current_time = time.time() if now is None else float(now)
    next_retry_at = float(
        cast("str | float", state.get("collection_resume_next_retry_at") or 0)
    )
    if next_retry_at > current_time:
        return {
            "pending": True,
            "attempted": False,
            "confirmed": False,
            "next_retry_at": next_retry_at,
            "state": state,
        }

    request_id = str(state.get("collection_resume_request_id") or "").strip()
    resume_scope = str(state.get("scope") or "").strip()
    if resume_scope:
        result = notify_collection_resume_after_cooldown(
            api_base_url,
            request_id,
            challenge_id=state.get("challenge_id"),
            scope=resume_scope,
        )
    else:
        result = notify_collection_resume_after_cooldown(
            api_base_url,
            request_id,
            challenge_id=state.get("challenge_id"),
        )
    request_attempts = max(1, int(result.get("request_attempts", 1) or 1))
    total_attempts = (
        int(cast("str | int", state.get("collection_resume_attempts", 0) or 0))
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
    if _resume_after_cooldown_response_confirmed(result, request_id):
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
            error = "NAS did not explicitly confirm collection resume"
    retry_delay = _auth_complete_retry_delay(total_attempts)
    state.update(
        {
            "collection_resume_pending": True,
            "collection_resume_attempts": total_attempts,
            "collection_resume_next_retry_at": current_time + retry_delay,
            "collection_resume_last_error": error[:1000],
        }
    )
    _save_fallback_state(state)
    return {
        "pending": True,
        "attempted": True,
        "confirmed": False,
        "next_retry_at": state["collection_resume_next_retry_at"],
        "result": result,
        "state": state,
    }


__all__ = (
    "FALLBACK_FAIL_THRESHOLD",
    "FALLBACK_STALL_SECONDS",
    "FALLBACK_STATE_PATH",
    "SLIDER_RETRY_INTERVAL_SECONDS",
    "SOLVER_COOLDOWN_FAIL_THRESHOLD",
    "SOLVER_COOLDOWN_SECONDS",
    "_begin_solver_cooldown_if_needed",
    "_default_fallback_state",
    "_load_fallback_state",
    "_manual_fallback_latch_active",
    "_mark_collection_resume_pending",
    "_new_collection_resume_request_id",
    "_node_solver_cooldown_can_resume",
    "_record_slider_attempt_failure",
    "_record_slider_attempt_started",
    "_report_manual_captcha",
    "_reset_fallback_state",
    "_retry_node_solver_blocked_report",
    "_retry_pending_collection_resume",
    "_save_fallback_state",
    "_slider_retry_due",
    "_solver_cooldown_active",
    "_sync_challenge_state",
    "manual_fallback_enabled",
)
