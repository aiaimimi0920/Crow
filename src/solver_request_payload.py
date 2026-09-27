"""Normalize solver requests without initializing the server runtime."""

import os
from urllib.parse import urlparse, urlsplit

from src.collection.adapters.taobao_solver_target import _normalize_solver_target_url


def _runtime_env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _real_taobao_auto_solver_enabled() -> bool:
    """Require an explicit production opt-in for automatic Taobao solving."""
    return _runtime_env_flag("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", False)


def _normalize_challenge_scope(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"list", "seed", "search", "listing"}:
        return "seed"
    if normalized in {"detail", "details", "item"}:
        return "detail"
    return ""


def _solver_target_requires_manual_only(solver_request: object) -> bool:
    request = solver_request if isinstance(solver_request, dict) else {}
    target_url = str(request.get("target_url") or request.get("url") or "").strip()
    if not target_url:
        return False
    try:
        hostname = str(urlsplit(target_url).hostname or "").strip().lower()
    except ValueError:
        return False
    is_taobao = hostname == "taobao.com" or hostname.endswith(".taobao.com")
    return bool(is_taobao and not _real_taobao_auto_solver_enabled())


def _normalize_solver_cdp_endpoint(value: object) -> str:
    cdp_endpoint = str(value or "").strip()
    runtime_endpoint = str(os.getenv("FAPAI_CDP_ENDPOINT") or "").strip().rstrip("/")

    if not cdp_endpoint:
        return runtime_endpoint
    if not runtime_endpoint:
        return cdp_endpoint

    try:
        requested = urlparse(cdp_endpoint)
        runtime = urlparse(runtime_endpoint)
    except ValueError:
        return cdp_endpoint

    if requested.hostname not in {"127.0.0.1", "localhost", "0.0.0.0"}:
        return cdp_endpoint

    scheme = runtime.scheme or requested.scheme or "http"
    host = runtime.hostname or requested.hostname
    port = requested.port or runtime.port
    if not host:
        return runtime_endpoint
    if port is None:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _build_solver_request(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}

    request: dict[str, str] = {}
    cdp_endpoint = _normalize_solver_cdp_endpoint(payload.get("cdp_endpoint"))
    target_url = _normalize_solver_target_url(
        payload.get("target_url") or payload.get("url")
    )
    challenge_target_url = _normalize_solver_target_url(
        payload.get("challenge_target_url")
    )

    if cdp_endpoint:
        request["cdp_endpoint"] = cdp_endpoint
    if target_url:
        request["target_url"] = target_url
    if challenge_target_url:
        request["challenge_target_url"] = challenge_target_url
    node_id = str(payload.get("node_id") or "").strip()
    if node_id:
        request["node_id"] = node_id
    cookie_snapshot_path = str(payload.get("cookie_snapshot_path") or "").strip()
    if cookie_snapshot_path:
        request["cookie_snapshot_path"] = cookie_snapshot_path
    scope = _normalize_challenge_scope(payload.get("scope"))
    if scope:
        request["scope"] = scope
    return request
