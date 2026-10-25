"""Read compatible scope status without losing an explicit operator pause."""

from collections.abc import Mapping


def operator_pause_requested(status: Mapping[str, object]) -> bool:
    if status.get("operator_paused") is True:
        return True
    if status.get("paused") is True and status.get("reason") == "operator_paused":
        return True
    solver = status.get("captcha_solver")
    return bool(
        isinstance(solver, dict)
        and solver.get("paused") is True
        and solver.get("pause_reason") == "operator"
    )


def collection_scope_statuses(status: Mapping[str, object]) -> dict[str, object]:
    scopes = status.get("collection_scopes")
    solver = status.get("captcha_solver")
    if isinstance(solver, dict):
        if not isinstance(scopes, dict):
            scopes = solver.get("collection_scopes")
        if not isinstance(scopes, dict):
            scopes = solver.get("scopes")
    return scopes if isinstance(scopes, dict) else {}
