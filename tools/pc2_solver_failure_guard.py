"""Revalidate request ownership before failure cleanup mutates browser targets."""

from __future__ import annotations

from src.collection.adapters.taobao_auth_target import same_auth_target
from tools.pc2_solver_scope_policy import (
    _challenge_scope_for_url,
    canonical_manual_challenge_target,
    node_solver_execution_block_reason,
    operator_pause_active,
    solver_request_target_url,
)


def failure_mutation_block_reason(
    started_status: dict[str, object],
    latest_status: object,
    target_url: str,
    cdp_endpoint: str,
    expected_node_id: str | None,
) -> str | None:
    """Never substitute the next available scope for the failed attempt's owner."""
    if not isinstance(latest_status, dict) or latest_status.get("error"):
        return "status_unavailable"
    if operator_pause_active(latest_status):
        return "operator_paused"
    scope = started_status.get("scope") or _challenge_scope_for_url(target_url)
    if scope not in ("seed", "detail"):
        return "request_scope_unavailable"
    projected = dict(latest_status)
    projected["scope"] = scope
    if "scopes" in latest_status or "collection_scopes" in latest_status:
        scopes = latest_status.get("scopes", latest_status.get("collection_scopes"))
        local = scopes.get(scope) if isinstance(scopes, dict) else None
        if not isinstance(local, dict) or local.get("error"):
            return "scope_status_unavailable"
        for key in (
            "paused",
            "manual_required",
            "last_status",
            "last_request",
            "challenge_id",
            "manual_only",
            "node_solver_blocked",
            "operator_paused",
            "force_reset_required",
            "force_unlock_flag_exists",
        ):
            projected[key] = local.get(key)
    elif latest_status.get("scope") not in (None, "", scope):
        return "request_scope_changed"
    current_id = str(projected.get("challenge_id") or "").strip()
    started_id = str(started_status.get("challenge_id") or "").strip()
    if (
        not current_id
        and projected.get("paused") is False
        and projected.get("manual_required") is False
        and projected.get("last_status") in ("manual_auth_completed", "solved")
    ):
        return "request_already_resolved"
    if current_id != started_id:
        return "request_identity_changed"
    reason = node_solver_execution_block_reason(
        projected, cdp_endpoint, expected_node_id
    )
    if reason:
        return reason
    if any(
        projected.get(key) is True
        for key in (
            "node_solver_blocked",
            "operator_paused",
            "force_reset_required",
            "force_unlock_flag_exists",
        )
    ):
        return "request_no_longer_eligible"
    requested_target = canonical_manual_challenge_target(
        solver_request_target_url(projected.get("last_request"))
    )
    if not same_auth_target(
        scope, canonical_manual_challenge_target(target_url), requested_target
    ):
        return "request_target_changed"
    return None
