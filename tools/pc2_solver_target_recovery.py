"""Recover a missing request page without replaying its unconfirmed navigation."""

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from tools.pc2_solver_maintenance import (
    MaintenanceNavigationUnconfirmed,
    pending_navigation_request_matches,
    pending_navigation_target_present,
    valid_target_directory,
)
from tools.pc2_solver_scope_policy import (
    _challenge_scope_for_url,
    canonical_manual_challenge_target,
)


def rebuild_missing_challenge_target(
    cdp_endpoint: str,
    target_url: str,
    *,
    solver_type: type[Any],
    read_json: Callable[..., object],
    open_target: Callable[[Any], dict[str, object] | None],
    pending_target: dict[str, object] | None = None,
) -> dict[str, object]:
    """Use a fresh directory for existence, never an uncertain reply as absence."""
    canonical_target = canonical_manual_challenge_target(target_url)
    scope = _challenge_scope_for_url(canonical_target)
    if scope not in {"seed", "detail"}:
        return {
            "attempted": False,
            "opened": False,
            "scope": scope,
            "reason": "invalid_collection_target",
        }

    opener = solver_type(cdp_endpoint=cdp_endpoint, target_url=canonical_target)
    requested_route = opener._solver_target_route(canonical_target)
    if not pending_navigation_request_matches(opener, pending_target):
        pending_target = None
    try:
        tabs = read_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        if not valid_target_directory(tabs):
            raise TypeError("Invalid CDP target directory")
    except Exception as exc:  # noqa: BLE001 -- retain structured CDP failure result
        return {
            "attempted": True,
            "opened": False,
            "scope": scope,
            "reason": "cdp_target_list_unavailable",
            "error_type": type(exc).__name__,
            **({"probe_target": pending_target} if pending_target else {}),
        }

    # Route evidence supersedes the pending blank-page record once navigation
    # becomes visible. An arbitrary unrelated blank page proves no ownership.
    for tab in tabs:
        if not isinstance(tab, dict) or tab.get("type") != "page":
            continue
        tab_url = str(tab.get("url") or "").strip()
        if not tab_url or solver_type._is_login_url(tab_url):
            continue
        if requested_route and opener._solver_target_route(tab_url) == requested_route:
            return {
                "attempted": False,
                "opened": False,
                "scope": scope,
                "reason": "request_target_already_present",
                "probe_target": {
                    "_target_id": str(tab.get("id") or "").strip(),
                    "_target_url": tab_url,
                    "_target_ws_url": str(
                        tab.get("webSocketDebuggerUrl") or ""
                    ).strip(),
                },
            }

    if pending_navigation_target_present(opener, tabs, pending_target):
        return {
            "attempted": False,
            "opened": False,
            "scope": scope,
            "reason": "target_navigation_pending",
            "probe_target": pending_target,
        }

    parsed = urlsplit(canonical_target)
    fresh_target = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "&".join(filter(None, (parsed.query, "__captcha_solver_bg=1"))),
            "",
        )
    )
    opener = solver_type(cdp_endpoint=cdp_endpoint, target_url=fresh_target)
    try:
        opened = open_target(opener)
    except MaintenanceNavigationUnconfirmed as deferred:
        return deferred.result(scope)
    if not isinstance(opened, dict):
        return {
            "attempted": True,
            "opened": False,
            "scope": scope,
            "reason": "missing_target_open_failed",
        }
    return {
        "attempted": True,
        "opened": True,
        "scope": scope,
        "reason": "missing_challenge_target_rebuilt",
        "probe_target": {
            "_target_id": str(opened.get("id") or "").strip(),
            "_target_url": str(opened.get("url") or fresh_target).strip(),
            "_target_ws_url": str(opened.get("webSocketDebuggerUrl") or "").strip(),
        },
    }
