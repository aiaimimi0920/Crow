"""Native scope projection, target identity and executor eligibility policy."""

from __future__ import annotations

from typing import cast
from urllib.parse import urlsplit, urlunsplit

from tools.pc2_solver_transport import real_taobao_auto_solver_enabled


def solver_request_target_urls(last_request: object) -> list[str]:
    if not isinstance(last_request, dict):
        return []
    targets = []
    for key in ("challenge_target_url", "target_url", "url"):
        target_url = str(last_request.get(key) or "").strip()
        if target_url and target_url not in targets:
            targets.append(target_url)
    return targets


def solver_request_target_url(last_request: object) -> str:
    targets = solver_request_target_urls(last_request)
    return targets[0] if targets else ""


def _solver_scope_statuses(solver_status: object) -> dict[str, object]:
    if not isinstance(solver_status, dict):
        return {}
    scopes = solver_status.get("scopes") or solver_status.get("collection_scopes")
    return dict(scopes) if isinstance(scopes, dict) else {}


def select_solver_scope_status(
    solver_status: object, preferred_challenge_id: object = None
) -> dict[str, object]:
    """Project aggregate NAS state onto one stable scoped challenge."""
    if not isinstance(solver_status, dict):
        return {}
    candidates: list[tuple[str, str, float, dict[str, object]]] = []
    for scope, scoped_status in _solver_scope_statuses(solver_status).items():
        if not isinstance(scoped_status, dict):
            continue
        challenge_id = str(scoped_status.get("challenge_id") or "").strip()
        if not challenge_id:
            continue
        first_seen = float(scoped_status.get("first_seen_epoch") or 0)
        candidates.append((str(scope), challenge_id, first_seen, scoped_status))
    if not candidates:
        return dict(solver_status)

    preferred = str(preferred_challenge_id or "").strip()
    selected = next((item for item in candidates if item[1] == preferred), None)
    if selected is None:
        selected = min(
            candidates,
            key=lambda item: (item[2] if item[2] > 0 else float("inf"), item[0]),
        )
    scope, challenge_id, _first_seen, scoped_status = selected
    scoped_request = scoped_status.get("last_request")
    projected = dict(solver_status)
    projected.update(
        {
            "scope": scope,
            "challenge_id": challenge_id,
            "paused": bool(scoped_status.get("paused")),
            "manual_required": bool(scoped_status.get("manual_required")),
            "manual_only": bool(scoped_status.get("manual_only")),
            "node_solver_blocked": bool(scoped_status.get("node_solver_blocked")),
            "last_status": scoped_status.get("last_status")
            or projected.get("last_status"),
            "last_failure_reason": scoped_status.get("last_failure_reason"),
            "last_request": dict(scoped_request)
            if isinstance(scoped_request, dict)
            else {},
        }
    )
    return projected


def _challenge_scope_for_url(url: object) -> str:
    value = str(url or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    host = str(parsed.hostname or "").strip().lower()
    path = str(parsed.path or "/").lower()
    while "//" in path:
        path = path.replace("//", "/")
    if host == "sf-item.taobao.com" or "/sf_item/" in path:
        return "detail"
    if host == "sf.taobao.com" and "/list/" in path:
        return "seed"
    return ""


def cdp_endpoint_matches_local(reported_cdp: str | None, local_cdp: str | None) -> bool:
    if not reported_cdp or not local_cdp:
        return False
    reported = reported_cdp.lower().strip().rstrip("/")
    local = local_cdp.lower().strip().rstrip("/")
    if reported == local:
        return True
    for loopback in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        if loopback in reported and loopback in local:
            return True
        if loopback in reported and "host.docker.internal" in local:
            return True
        if loopback in reported and "192.168.65.254" in local:
            return True
    return False


def node_owns_last_request(
    solver_status: dict[str, object],
    local_cdp_endpoint: str,
    expected_node_id: str | None = None,
) -> bool:
    last_request = solver_status.get("last_request")
    if not isinstance(last_request, dict):
        return False
    node_id = str(last_request.get("node_id") or "").strip().lower()
    if expected_node_id and node_id == expected_node_id.strip().lower():
        return True
    reported_cdp = str(last_request.get("cdp_endpoint") or "").strip()
    return bool(
        reported_cdp and cdp_endpoint_matches_local(reported_cdp, local_cdp_endpoint)
    )


def solver_status_requires_manual_only(solver_status: object) -> bool:
    if not isinstance(solver_status, dict):
        return False
    if solver_status.get("manual_only") is True:
        return True
    last_request = solver_status.get("last_request")
    if not isinstance(last_request, dict):
        return False
    target_url = str(
        last_request.get("target_url") or last_request.get("url") or ""
    ).strip()
    try:
        hostname = str(urlsplit(target_url).hostname or "").strip().lower()
    except ValueError:
        return False
    is_taobao = hostname == "taobao.com" or hostname.endswith(".taobao.com")
    return bool(is_taobao and not real_taobao_auto_solver_enabled())


def manual_challenge_registration_needed(solver_status: dict[str, object]) -> bool:
    return bool(
        solver_status_requires_manual_only(solver_status)
        and not (
            solver_status.get("manual_required") is True
            and str(solver_status.get("challenge_id") or "").strip()
        )
    )


def canonical_manual_challenge_target(value: object) -> str:
    from src.collection.adapters.taobao_auth_target import canonical_auth_target

    target_url = str(value or "").strip()
    try:
        parsed = urlsplit(target_url)
    except ValueError:
        return ""
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname or not (
        hostname == "taobao.com" or hostname.endswith(".taobao.com")
    ):
        return ""
    scope = _challenge_scope_for_url(target_url)
    if scope in {"seed", "detail"}:
        try:
            return cast(str, canonical_auth_target(scope, target_url))
        except (ValueError, TypeError):
            return ""
    path = parsed.path.split("/_____tmd_____/punish", 1)[0]
    while "//" in path:
        path = path.replace("//", "/")
    return urlunsplit((parsed.scheme or "https", parsed.netloc, path or "/", "", ""))


def node_solver_execution_block_reason(
    solver_status: object,
    local_cdp_endpoint: str,
    expected_node_id: str | None = None,
) -> str | None:
    """Fail closed unless this node is the sole eligible challenge executor."""
    if not isinstance(solver_status, dict) or solver_status.get("error"):
        return "status_unavailable"
    if solver_status_requires_manual_only(solver_status):
        return "manual_only"
    if solver_status.get("running") is True:
        return "nas_solver_running"
    if not node_owns_last_request(solver_status, local_cdp_endpoint, expected_node_id):
        return "request_owned_elsewhere"
    return None


__all__ = (
    "_challenge_scope_for_url",
    "_solver_scope_statuses",
    "canonical_manual_challenge_target",
    "cdp_endpoint_matches_local",
    "manual_challenge_registration_needed",
    "node_owns_last_request",
    "node_solver_execution_block_reason",
    "select_solver_scope_status",
    "solver_request_target_url",
    "solver_request_target_urls",
    "solver_status_requires_manual_only",
)
