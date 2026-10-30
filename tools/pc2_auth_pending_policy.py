"""Admission for relinquishing a failed local detail confirmation wait."""

from __future__ import annotations

from typing import cast

from src.collection.adapters.taobao_auth_target import canonical_auth_target
from tools.pc2_solver_scope_policy import (
    node_owns_last_request,
    operator_pause_active,
    solver_request_target_url,
    solver_status_requires_manual_only,
)


def _target(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        return cast(str, canonical_auth_target("detail", value))
    except (TypeError, ValueError):
        return ""


def bound_unhealthy_detail_confirmation(
    state: dict[str, object],
    status: object,
    cdp_endpoint: str,
    expected_node_id: str | None,
) -> bool:
    """A terminal failure is not an ACK or permission to operate a browser.

    The caller enforces the existing timeout. Releasing only local wait fields
    returns arbitration to fresh control reads, including pending force resets.
    """
    if state.get("scope") != "detail" or any(
        state.get(key) is not False
        for key in ("manual_pushed", "terminal_manual_pending")
    ):
        return False
    completion, challenge = state.get("auth_completion_id"), state.get("challenge_id")
    if not all(
        isinstance(value, str) and value.strip() for value in (completion, challenge)
    ):
        return False
    if not isinstance(status, dict) or status.get("error"):
        return False
    if status.get("global_manual_pause_active") is not False or operator_pause_active(
        status
    ):
        return False
    if status.get("running") is not False:
        return False
    if any(
        status.get(key, False) is not False
        for key in ("running", "queued", "nas_solver_active", "operator_paused")
    ):
        return False
    scopes = (
        status.get("scopes") if "scopes" in status else status.get("collection_scopes")
    )
    row = scopes.get("detail") if isinstance(scopes, dict) else None
    if not isinstance(row, dict) or row.get("scope") != "detail" or row.get("error"):
        return False
    if row.get("challenge_id") != challenge or row.get("paused") is not True:
        return False
    if any(
        row.get(key) is not False
        for key in ("manual_required", "manual_only", "node_solver_blocked")
    ):
        return False
    # A pending force reset is control work, not a reason to restart this proof.
    if type(row.get("force_reset_required")) is not bool:
        return False
    if operator_pause_active(row) or row.get("operator_paused", False) is not False:
        return False
    if row.get("running", False) is not False:
        return False
    if solver_status_requires_manual_only(row):
        return False
    request = row.get("last_request")
    if not isinstance(request, dict) or request.get("scope") != "detail":
        return False
    target = _target(state.get("auth_complete_target_url"))
    if not target or target != _target(solver_request_target_url(request)):
        return False
    # Reuse the executor's explicit-node-first ownership rule, not a new alias.
    if not node_owns_last_request(row, cdp_endpoint, expected_node_id):
        return False
    snapshot = status.get("cookie_snapshot_refresh")
    if not isinstance(snapshot, dict) or any(
        snapshot.get(key) != value
        for key, value in (
            ("scope", "detail"),
            ("completion_id", completion),
            ("expected_challenge_id", challenge),
            ("status", "failed"),
        )
    ):
        return False
    if (
        snapshot.get("refreshed") is not False
        or snapshot.get("retry_queued") is not False
    ):
        return False
    if (
        "next_retry_at_epoch" not in snapshot
        or snapshot["next_retry_at_epoch"] is not None
    ):
        return False
    if snapshot.get("auth_finalize_requested") is not True:
        return False
    # Ordinary unhealthy failures in the existing schema omit this field.
    if snapshot.get("auth_state_confirmed", False) is not False:
        return False
    attempts, maximum = snapshot.get("attempts"), snapshot.get("max_attempts")
    if (
        type(attempts) is not int
        or type(maximum) is not int
        or not (attempts == maximum and attempts > 0)
    ):
        return False
    result = snapshot.get("result")
    return bool(
        isinstance(result, dict)
        and result.get("refreshed") is False
        and result.get("reason") == "cookie_snapshot_candidate_unhealthy"
    )
