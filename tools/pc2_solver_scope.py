from __future__ import annotations

import time
from typing import Protocol, cast

from tools.internal_api_http import fetch_json, post_json
from tools.pc2_solver_scope_policy import (
    _challenge_scope_for_url,
    _solver_scope_statuses,
    canonical_manual_challenge_target,
    cdp_endpoint_matches_local,
    manual_challenge_registration_needed,
    node_owns_last_request,
    node_solver_execution_block_reason,
    select_solver_scope_status,
    solver_request_target_url,
    solver_request_target_urls,
    solver_status_requires_manual_only,
)
from tools.pc2_solver_transport import (
    _captcha_report_url,
    _force_reset_url,
    _manual_captcha_report_url,
)


class ScopeSolver(Protocol):
    def _close_cdp_target(self, target_id: str) -> bool: ...

    def _prune_duplicate_challenge_tabs(
        self, tabs: list[object]
    ) -> dict[str, object]: ...


def _create_scope_solver(
    *, cdp_endpoint: str, target_url: str | None = None
) -> ScopeSolver:
    from src.captcha_solver import CaptchaSolver

    return cast(
        ScopeSolver, CaptchaSolver(cdp_endpoint=cdp_endpoint, target_url=target_url)
    )


def notify_force_reset(
    api_base: str, scope: str, challenge_id: str
) -> dict[str, object]:
    try:
        payload = post_json(
            _force_reset_url(api_base),
            {
                "source": "pc2_local_solver",
                "scope": scope,
                "challenge_id": challenge_id,
            },
            timeout=10,
        )
        return (
            payload if isinstance(payload, dict) else {"ok": False, "payload": payload}
        )
    except Exception as exc:  # noqa: BLE001 -- preserve the notification/probe failure envelope
        return {"ok": False, "error": repr(exc)}


def close_challenge_pages_for_scope(
    cdp_endpoint: str, scope: object
) -> dict[str, object]:
    """Close all CDP collection/challenge tabs for one scope after force reset."""
    normalized = str(scope or "").strip().lower()
    if normalized not in {"seed", "detail"}:
        return {"attempted": False, "closed": 0, "reason": "invalid_scope"}
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
    except Exception as exc:  # noqa: BLE001 -- preserve the notification/probe failure envelope
        return {"attempted": True, "closed": 0, "error": repr(exc)}
    closed = []
    closer = _create_scope_solver(cdp_endpoint=cdp_endpoint)
    for tab in tabs if isinstance(tabs, list) else []:
        if not isinstance(tab, dict) or tab.get("type") != "page":
            continue
        target_id = str(tab.get("id") or "").strip()
        target_url = str(tab.get("url") or "").strip()
        if not target_id or target_url.lower() == "about:blank":
            continue
        if _challenge_scope_for_url(target_url) != normalized:
            continue
        try:
            if closer._close_cdp_target(target_id):
                closed.append(target_id)
        except Exception:  # noqa: BLE001, S112 -- a failed target/probe must not block the remaining ones
            continue
    return {
        "attempted": True,
        "closed": len(closed),
        "target_ids": closed,
        "scope": normalized,
    }


def compact_active_challenge_pages(
    cdp_endpoint: str, solver_status: object
) -> dict[str, object]:
    """Keep at most one active challenge page for each independent scope."""
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
    except Exception as exc:  # noqa: BLE001 -- preserve the notification/probe failure envelope
        return {"attempted": True, "closed": 0, "error": repr(exc), "scopes": {}}
    if not isinstance(tabs, list):
        return {
            "attempted": True,
            "closed": 0,
            "error": "invalid_cdp_tab_list",
            "scopes": {},
        }

    results = {}
    total_closed = 0
    for scope, scoped_status in _solver_scope_statuses(solver_status).items():
        if scope not in {"seed", "detail"} or not isinstance(scoped_status, dict):
            continue
        if not str(scoped_status.get("challenge_id") or "").strip():
            continue
        target_url = solver_request_target_url(scoped_status.get("last_request"))
        if not target_url:
            continue
        solver = _create_scope_solver(cdp_endpoint=cdp_endpoint, target_url=target_url)
        pruning = solver._prune_duplicate_challenge_tabs(tabs)
        results[scope] = pruning
        closed = int(cast("str | int", pruning.get("closed") or 0))
        total_closed += closed
        if closed:
            try:
                refreshed_tabs = fetch_json(
                    f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5
                )
                if isinstance(refreshed_tabs, list):
                    tabs = refreshed_tabs
            except Exception:  # noqa: BLE001, S110 -- retain the last tab snapshot if refresh fails
                pass
    return {"attempted": True, "closed": total_closed, "scopes": results}


def check_cdp_healthy(cdp_endpoint: str) -> bool:
    endpoint = cdp_endpoint.rstrip("/")
    for p in ("/json/list", "/json/version"):
        try:
            resp = fetch_json(f"{endpoint}{p}", timeout=5)
            if resp is not None:
                return True
        except Exception:  # noqa: BLE001, S112 -- a failed target/probe must not block the remaining ones
            continue
    return False


def notify_manual_challenge(
    api_base: str, solver_status: dict[str, object], expected_node_id: str | None = None
) -> dict[str, object]:
    last_request = (
        solver_status.get("last_request") if isinstance(solver_status, dict) else None
    )
    if not isinstance(last_request, dict):
        return {"ok": False, "error": "missing_last_request"}
    target_url = canonical_manual_challenge_target(
        last_request.get("target_url") or last_request.get("url")
    )
    if not target_url:
        return {"ok": False, "error": "missing_safe_target_url"}
    payload: dict[str, object] = {
        "target_url": target_url,
        "url": target_url,
        "node_id": str(expected_node_id or last_request.get("node_id") or "").strip(),
        "cdp_endpoint": str(last_request.get("cdp_endpoint") or "").strip(),
        "manual_only": True,
        "timestamp": int(time.time() * 1000),
    }
    scope = str(solver_status.get("scope") or "").strip()
    if solver_status.get("challenge_id"):
        payload["challenge_id"] = solver_status["challenge_id"]
    if scope:
        payload["scope"] = scope
    try:
        response = post_json(_manual_captcha_report_url(api_base), payload, timeout=10)
    except Exception as exc:  # noqa: BLE001 -- preserve the notification/probe failure envelope
        return {"ok": False, "error": repr(exc)}
    return (
        dict(response)
        if isinstance(response, dict)
        else {"ok": False, "error": "non_dict_response"}
    )


def notify_solver_blocked(
    api_base: str,
    solver_status: dict[str, object],
    fallback_state: dict[str, object],
    expected_node_id: str | None = None,
) -> dict[str, object]:
    last_request = (
        solver_status.get("last_request") if isinstance(solver_status, dict) else None
    )
    if not isinstance(last_request, dict):
        return {"ok": False, "error": "missing_last_request"}
    target_url = canonical_manual_challenge_target(
        last_request.get("target_url") or last_request.get("url")
    )
    if not target_url:
        return {"ok": False, "error": "missing_safe_target_url"}
    payload = {
        "target_url": target_url,
        "url": target_url,
        "node_id": str(expected_node_id or last_request.get("node_id") or "").strip(),
        "cdp_endpoint": str(last_request.get("cdp_endpoint") or "").strip(),
        "challenge_id": str(solver_status.get("challenge_id") or "").strip() or None,
        "node_solver_blocked": True,
        "node_solver_blocked_reason": str(
            fallback_state.get("solver_cooldown_reason") or "repeated_solver_failures"
        ).strip(),
        "node_solver_blocked_attempts": int(
            cast(
                "str | int",
                fallback_state.get(
                    "slider_attempts", fallback_state.get("consecutive_failures", 0)
                )
                or 0,
            )
        ),
        "timestamp": int(time.time() * 1000),
    }
    scope = str(solver_status.get("scope") or fallback_state.get("scope") or "").strip()
    if scope:
        payload["scope"] = scope
    try:
        response = post_json(_captcha_report_url(api_base), payload, timeout=10)
    except Exception as exc:  # noqa: BLE001 -- preserve the notification/probe failure envelope
        return {"ok": False, "error": repr(exc)}
    return (
        dict(response)
        if isinstance(response, dict)
        else {"ok": False, "error": "non_dict_response"}
    )


__all__ = (
    "_challenge_scope_for_url",
    "_solver_scope_statuses",
    "canonical_manual_challenge_target",
    "cdp_endpoint_matches_local",
    "check_cdp_healthy",
    "close_challenge_pages_for_scope",
    "compact_active_challenge_pages",
    "manual_challenge_registration_needed",
    "node_owns_last_request",
    "node_solver_execution_block_reason",
    "notify_force_reset",
    "notify_manual_challenge",
    "notify_solver_blocked",
    "select_solver_scope_status",
    "solver_request_target_url",
    "solver_request_target_urls",
    "solver_status_requires_manual_only",
)
