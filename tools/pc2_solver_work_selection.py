"""Select runnable scoped work without changing stable receipt projection."""

from __future__ import annotations

from typing import TypeGuard

from tools.pc2_solver_scope_policy import (
    _challenge_scope_for_url,
    node_owns_last_request,
    node_solver_execution_block_reason,
    select_solver_scope_status,
    solver_request_target_url,
)

_SCOPES = {"seed", "detail"}


def _scopes(status: dict[str, object]) -> dict[str, object]:
    # An explicit empty/invalid modern field must not revive stale legacy work.
    value = (
        status.get("scopes") if "scopes" in status else status.get("collection_scopes")
    )
    return value if isinstance(value, dict) else {}


def _owned_scope(
    row: object, scope: str, cdp_endpoint: str, expected_node_id: str | None
) -> TypeGuard[dict[str, object]]:
    if not isinstance(row, dict) or not str(row.get("challenge_id") or "").strip():
        return False
    request = row.get("last_request")
    if not isinstance(request, dict) or request.get("scope", scope) != scope:
        return False
    if _challenge_scope_for_url(solver_request_target_url(request)) != scope:
        return False
    return node_owns_last_request(row, cdp_endpoint, expected_node_id)


def _switch_allowed(status: dict[str, object], state: dict[str, object]) -> bool:
    if status.get("error") or status.get("scope") not in _SCOPES:
        return False
    if status.get("pause_reason") not in {"captcha_solver", "manual_required"}:
        return False
    if status.get("operator_paused", False) is not False:
        return False
    if "global_manual_pause_active" in status:
        if status["global_manual_pause_active"] is not False:
            return False
        if type(status.get("force_unlock_flag_exists")) is not bool:
            return False
    elif status.get("force_unlock_flag_exists") is not False:
        return False
    if any(
        status.get(key) is not False
        for key in (
            "running",
            "queued",
            "nas_solver_active",
        )
    ):
        return False
    if any(
        state.get(key) is not False
        for key in (
            "auth_complete_pending",
            "collection_resume_pending",
            "terminal_manual_pending",
        )
    ):
        return False
    # Even an expired cooldown must finish its original report/resume ACK path.
    return not any(
        state.get(key)
        for key in (
            "solver_cooldown_until",
            "solver_cooldown_reason",
            "slider_attempt_started_at",
            "node_solver_blocked_reported",
            "node_solver_blocked_report_attempts",
            "node_solver_blocked_report_next_retry_at",
        )
    )


def select_solver_work_status(
    solver_status: dict[str, object],
    fallback_state: dict[str, object],
    cdp_endpoint: str,
    expected_node_id: str | None = None,
) -> dict[str, object]:
    """Only bypass an acknowledged scoped manual wait, never a global control gate.

    This is initial work arbitration, not execution authorization. The loop keeps
    its pending-control priority, manual window, shared backpressure and fresh
    execution-boundary projection. Authentication ACKs use the stable selector.
    """
    selected = select_solver_scope_status(
        solver_status, preferred_challenge_id=fallback_state.get("challenge_id")
    )
    if not _switch_allowed(solver_status, fallback_state):
        return selected
    scopes = _scopes(solver_status)
    scope = str(selected.get("scope") or "")
    row = scopes.get(scope)
    if scope not in _SCOPES or not _owned_scope(
        row, scope, cdp_endpoint, expected_node_id
    ):
        return selected
    if any(
        row.get(key) is not True for key in ("paused", "manual_required", "manual_only")
    ):
        return selected
    if any(
        row.get(key) is not False
        for key in ("node_solver_blocked", "force_reset_required")
    ):
        return selected
    current_id = fallback_state.get("challenge_id")
    if not current_id and fallback_state.get("manual_pushed") is not False:
        # An unbound legacy latch cannot be expired by generation synchronization.
        return selected
    if current_id and (
        current_id != row["challenge_id"] or fallback_state.get("scope") != scope
    ):
        return selected
    # An unscoped legacy manual policy is not just another scoped manual wait.
    active = scopes.get(solver_status.get("scope"))
    if solver_status.get("manual_only") is True and (
        not isinstance(active, dict) or active.get("manual_only") is not True
    ):
        return selected
    candidates = {}
    for name in sorted(_SCOPES - {scope}):
        candidate = scopes.get(name)
        if not _owned_scope(candidate, name, cdp_endpoint, expected_node_id):
            continue
        if candidate.get("paused") is not True or any(
            candidate.get(key) is not False
            for key in (
                "manual_required",
                "manual_only",
                "node_solver_blocked",
                "force_reset_required",
            )
        ):
            continue
        projected = select_solver_scope_status(solver_status, candidate["challenge_id"])
        if (
            node_solver_execution_block_reason(
                projected, cdp_endpoint, expected_node_id
            )
            is None
        ):
            candidates[name] = candidate
    if not candidates:
        return selected
    eligible = dict(solver_status, scopes=candidates)
    work = select_solver_scope_status(eligible)
    return select_solver_scope_status(solver_status, work["challenge_id"])
