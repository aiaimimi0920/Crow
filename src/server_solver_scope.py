from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from .collection.adapters.taobao_solver_target import (
    _solver_request_scope_from_target_url,
)
from .collection_control_state import CHALLENGE_SCOPES, new_scope_state
from .server_http_responses import _is_client_disconnect_error
from .solver_request_payload import (
    _normalize_challenge_scope,
    _real_taobao_auto_solver_enabled,
    _runtime_env_flag,
)
from .solver_scope_runtime import SolverScopeRuntime


def _challenge_scope_for_request(request_payload: object) -> str:
    payload = request_payload if isinstance(request_payload, dict) else {}
    explicit = _normalize_challenge_scope(payload.get("scope"))
    if explicit:
        return explicit
    target_url = str(
        payload.get("challenge_target_url")
        or payload.get("target_url")
        or payload.get("url")
        or ""
    )
    return _normalize_challenge_scope(_solver_request_scope_from_target_url(target_url))


def _new_solver_scope_state() -> dict[str, object]:
    return new_scope_state()


def _force_reset_solver_scope(
    scope: str | None,
    challenge_id: str | None = None,
    *,
    scopes: SolverScopeRuntime,
    clear_challenge: Callable[[str], str | None],
    remember_reset: Callable[[str, dict[str, object]], None],
    solver_status: Callable[[], dict[str, object]],
    report_grace_seconds: float,
) -> dict[str, object]:
    """Reset one stuck list/detail challenge after the safety timeout."""
    with scopes.runtime.lock:
        result = _force_reset_solver_scope_locked(
            scope,
            challenge_id,
            scopes=scopes,
            clear_challenge=clear_challenge,
            remember_reset=remember_reset,
            report_grace_seconds=report_grace_seconds,
        )
    if result.get("force_reset") is True:
        result["captcha_solver"] = solver_status()
    return result


def _force_reset_solver_scope_locked(
    scope: str | None,
    challenge_id: str | None,
    *,
    scopes: SolverScopeRuntime,
    clear_challenge: Callable[[str], str | None],
    remember_reset: Callable[[str, dict[str, object]], None],
    report_grace_seconds: float,
) -> dict[str, object]:
    normalized_scope = _normalize_challenge_scope(scope)
    if normalized_scope not in CHALLENGE_SCOPES:
        return {
            "ok": False,
            "force_reset": False,
            "error": "scope must be seed or detail",
        }
    status = scopes.status(normalized_scope)
    active_id = str(status.get("challenge_id") or "").strip()
    reported_id = str(challenge_id or "").strip()
    if not active_id:
        return {
            "ok": True,
            "force_reset": False,
            "scope": normalized_scope,
            "reason": "no_active_challenge",
        }
    if reported_id and reported_id != active_id:
        return {
            "ok": False,
            "force_reset": False,
            "scope": normalized_scope,
            "challenge_id": active_id,
            "stale_challenge": True,
            "error": "challenge_id does not match the active scoped challenge",
        }
    age = float(cast("str | float", status.get("challenge_age_seconds") or 0))
    if age < scopes.force_reset_seconds:
        return {
            "ok": False,
            "force_reset": False,
            "scope": normalized_scope,
            "challenge_id": active_id,
            "challenge_age_seconds": age,
            "retry_after_seconds": max(
                0, int(math.ceil(scopes.force_reset_seconds - age))
            ),
            "error": "challenge has not reached the force-reset safety timeout",
        }
    recovery_request = dict(
        cast("Mapping[str, object]", status.get("last_request") or {})
    )
    clear_error = clear_challenge(normalized_scope)
    if clear_error:
        return {
            "ok": False,
            "force_reset": False,
            "scope": normalized_scope,
            "challenge_id": active_id,
            "error": clear_error,
        }
    scopes.set_pause(False, scope=normalized_scope)
    try:
        Path(scopes.manual_flag_path(normalized_scope)).unlink(missing_ok=True)
    except Exception:
        pass
    # The legacy flag is aggregate state.  Once the reset scope is clear, only
    # keep it if another independent scope still requires manual recovery;
    # otherwise it would continue to report a global pause after both scoped
    # collectors have resumed.
    try:
        other_scope_requires_manual = any(
            bool(scopes.read(candidate).get("manual_required"))
            for candidate in CHALLENGE_SCOPES
            if candidate != normalized_scope
        )
        if not other_scope_requires_manual:
            Path(scopes.manual_flag_path()).unlink(missing_ok=True)
    except Exception:
        pass
    remember_reset(normalized_scope, recovery_request)
    return {
        "ok": True,
        "force_reset": True,
        "scope": normalized_scope,
        "previous_challenge_id": active_id,
        "challenge_age_seconds": age,
        "report_grace_seconds": report_grace_seconds,
        "paused": scopes.effectively_paused(),
    }


__all__ = [
    "SolverScopeRuntime",
    "_runtime_env_flag",
    "_real_taobao_auto_solver_enabled",
    "_normalize_challenge_scope",
    "_challenge_scope_for_request",
    "_new_solver_scope_state",
    "_force_reset_solver_scope",
    "_is_client_disconnect_error",
]
