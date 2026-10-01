"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.seed_collector_context import *


def _extract_seed_items(
    parser_or_probe: Any,
    html: str,
    *,
    final_url: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    parser: SeedListParser = (
        parser_or_probe
        if callable(getattr(parser_or_probe, "parse", None))
        else TaobaoSeedListParser(parser_or_probe)
    )
    result = parser.parse(html, final_url=final_url)
    return [dict(item) for item in result.items], dict(result.summary), result.has_challenge


def _browser_page_payload_missing_without_challenge(fetch_method: str, list_summary: dict[str, Any]) -> bool:
    if not str(fetch_method or "").startswith("browser_page"):
        return False
    if not isinstance(list_summary, dict):
        return True
    has_script = list_summary.get("has_script")
    item_count = list_summary.get("item_count")
    return has_script is False and item_count is None


def _write_runtime_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "seed_collector_summary.json", summary)


def _collection_pause_state(api_base_url: str) -> dict[str, Any]:
    if not str(api_base_url or "").strip():
        return {"paused": False, "reason": "status_probe_disabled"}

    endpoint = api_base_url.rstrip("/") + "/status"
    try:
        payload = fetch_json(endpoint, timeout=5)
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"paused": False, "reason": "status_unavailable", "error": safe_exception_text(exc)}

    if not isinstance(payload, dict):
        return {"paused": False, "reason": "status_unavailable", "error": "non_object_status"}

    return _normalize_collection_pause_state(payload, scope="seed")


def _normalize_collection_pause_state(payload: dict[str, Any], scope: str = "seed") -> dict[str, Any]:
    captcha_solver = payload.get("captcha_solver")
    if not isinstance(captcha_solver, dict):
        captcha_solver = {}
    scope_statuses = payload.get("collection_scopes")
    if not isinstance(scope_statuses, dict):
        scope_statuses = captcha_solver.get("collection_scopes")
    if not isinstance(scope_statuses, dict):
        scope_statuses = captcha_solver.get("scopes")
    scoped = scope_statuses.get(scope) if isinstance(scope_statuses, dict) else None
    if isinstance(scoped, dict):
        scoped_solver = dict(captcha_solver)
        scoped_solver.update(scoped)
        scoped_solver["last_request"] = scoped.get("last_request") or captcha_solver.get("last_request") or {}
        scoped_solver["running"] = bool(scoped.get("last_status") == "running")
        scoped_solver["paused"] = bool(scoped.get("paused"))
        scoped_solver["manual_required"] = bool(scoped.get("manual_required"))
        scoped_solver["force_unlock_flag_exists"] = False
        return {
            "paused": bool(scoped.get("paused") or scoped.get("manual_required")),
            "reason": "captcha_solver_manual_required" if scoped.get("manual_required") else "captcha_solver_running" if scoped.get("paused") else None,
            "captcha_solver": scoped_solver,
            "scope": scope,
        }
    manual_required = bool(captcha_solver.get("manual_required"))
    force_unlock = bool(captcha_solver.get("force_unlock_flag_exists"))
    solver_running_for_current_node = _captcha_solver_targets_current_node(captcha_solver)
    solver_running_only = (
        bool(payload.get("paused"))
        and bool(captcha_solver.get("running"))
        and bool(captcha_solver.get("paused"))
        and not manual_required
        and not force_unlock
    )
    paused = bool(payload.get("paused")) or manual_required or force_unlock or solver_running_for_current_node
    if solver_running_only and not solver_running_for_current_node:
        paused = False
    reason = "captcha_solver_manual_required" if manual_required else "collection_paused" if paused else None
    if solver_running_for_current_node and not manual_required and not force_unlock:
        reason = "captcha_solver_running"
    elif solver_running_only:
        reason = "captcha_solver_running_other_node"
    return {
        "paused": paused,
        "reason": reason,
        "captcha_solver": captcha_solver,
    }


def _captcha_solver_targets_current_node(captcha_solver: dict[str, Any]) -> bool:
    if not bool(captcha_solver.get("running")):
        return False
    last_request = captcha_solver.get("last_request")
    if not isinstance(last_request, dict):
        return True
    target_node_id = str(last_request.get("node_id") or "").strip().casefold()
    current_node_id = str(project_getenv("CROW_NODE_ID") or "").strip().casefold()
    if not target_node_id or not current_node_id:
        return True
    return target_node_id == current_node_id


def _collection_pause_state_with_retry(api_base_url: str) -> dict[str, Any]:
    pause_state = _collection_pause_state(api_base_url)
    if not str(api_base_url or "").strip() or pause_state.get("reason") != "status_unavailable":
        return pause_state

    for _attempt in range(1, STATUS_UNAVAILABLE_RETRY_ATTEMPTS):
        time.sleep(STATUS_UNAVAILABLE_RETRY_SLEEP_SECONDS)
        retry_state = _collection_pause_state(api_base_url)
        pause_state = retry_state
        if retry_state.get("reason") != "status_unavailable":
            break
    return pause_state


def _pause_state_targets_detail_page(pause_state: dict[str, Any]) -> bool:
    # The legacy facade clones this function with its own globals.
    from src.collection.adapters.taobao_solver_target import _solver_request_scope_from_target_url

    captcha_solver = pause_state.get("captcha_solver")
    if not isinstance(captcha_solver, dict):
        return False
    last_request = captcha_solver.get("last_request")
    if not isinstance(last_request, dict):
        return False
    target_url = str(last_request.get("target_url") or "")
    return _solver_request_scope_from_target_url(target_url) == "detail"


def _default_seed_auth_probe_target_url() -> str:
    return "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"


def _normalize_seed_challenge_target_url(target_url: str, *, allow_default: bool = False) -> str:
    fallback = _default_seed_auth_probe_target_url() if allow_default else ""
    try:
        parsed = urlsplit(target_url)
    except ValueError:
        return fallback
    if str(parsed.hostname or "").casefold() != "sf.taobao.com":
        return fallback

    path = str(parsed.path or "")
    punish_index = path.casefold().find("/_____tmd_____/punish")
    if punish_index >= 0:
        path = path[:punish_index]
    while "//" in path:
        path = path.replace("//", "/")
    if not path.lower().startswith("/list/"):
        return fallback

    allowed_query_keys = {"location_code", "st_param", "auction_start_seg", "page"}
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key in allowed_query_keys
    ]
    query_pairs.append(("__captcha_solver_bg", "1"))
    return urlunsplit(("https", "sf.taobao.com", path, urlencode(query_pairs, doseq=True), ""))


def _pause_state_seed_probe_target_url(pause_state: dict[str, Any], *, allow_default: bool = False) -> str:
    captcha_solver = pause_state.get("captcha_solver")
    if not isinstance(captcha_solver, dict):
        return _default_seed_auth_probe_target_url() if allow_default else ""
    allow_default = allow_default and not captcha_solver.get("challenge_id")
    last_request = captcha_solver.get("last_request")
    if not isinstance(last_request, dict):
        return _default_seed_auth_probe_target_url() if allow_default else ""
    target_url = str(last_request.get("challenge_target_url") or last_request.get("target_url")
                     or last_request.get("url") or "").strip()
    return _normalize_seed_challenge_target_url(target_url, allow_default=allow_default)


def _pause_state_blocks_seed_stage(pause_state: dict[str, Any]) -> bool:
    if not pause_state.get("paused"):
        return False
    if pause_state.get("scope") == "seed":
        return True
    return not _pause_state_targets_detail_page(pause_state)


def _notify_auth_probe_passed(api_base_url: str, target_url: str) -> dict[str, Any]:
    if not str(api_base_url or "").strip():
        return {"ok": False, "skipped": True, "reason": "api_base_url_missing"}
    endpoint = api_base_url.rstrip("/") + "/collection/auth/complete"
    payload = post_json(
        endpoint,
        {
            "source": "seed_auth_probe",
            "scope": "seed",
            "refresh_cookie_snapshot": False,
            "target_url": target_url,
        },
        timeout=10,
    )
    return payload if isinstance(payload, dict) else {"ok": False, "payload": payload}


def _probe_seed_auth_state(
    config: SeedCollectorConfig,
    pause_state: dict[str, Any],
    *,
    http_session: Any,
    browserless_seed_probe: Any,
) -> dict[str, Any]:
    from src.collection.adapters.taobao_auth_target import seed_payload_is_authenticated

    target_url = _pause_state_seed_probe_target_url(
        pause_state,
        allow_default=bool(str(config.api_base_url or "").strip()),
    )
    if not target_url:
        return {"attempted": False, "authenticated": False, "reason": "no_seed_list_target_url"}

    try:
        runtime_user_agent = resolve_runtime_user_agent(config.cdp_endpoint)
        html, final_url, status_code, fetch_method = fetch_list_page(
            http_session,
            cdp_endpoint=config.cdp_endpoint,
            target_url=target_url,
            user_agent=runtime_user_agent or getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT),
            solver_enabled=False,
            api_base_url=config.api_base_url,
        )
        items, list_summary, _ = _extract_seed_items(browserless_seed_probe, html, final_url=final_url)
        payload = browserless_seed_probe.extract_list_payload(html)
        authenticated = seed_payload_is_authenticated(payload, list_summary, final_url=final_url, target_url=target_url)
        authenticated = authenticated and (status_code is None or 200 <= status_code < 300)
        result: dict[str, Any] = {
            "attempted": True,
            "authenticated": authenticated,
            "target_url": target_url,
            "final_url": final_url,
            "status_code": status_code,
            "method": fetch_method,
            "item_count": len(items),
            "list_summary": list_summary,
        }
        if not authenticated:
            result["reason"] = "probe_not_authenticated"
        if authenticated:
            completion = _notify_auth_probe_passed(config.api_base_url, target_url)
            result["auth_complete"] = completion
            confirmed = (completion.get("ok") is True and completion.get("auth_state_confirmed") is True
                         and completion.get("scope") == "seed"
                         and not completion.get("scope_paused") and not completion.get("scope_manual_required"))
            if not confirmed:
                result["authenticated"] = False
                result["reason"] = ("auth_confirmation_pending" if completion.get("auth_confirmation_pending")
                                    else "auth_completion_rejected")
        return result
    except Exception as exc:
        return {
            "attempted": True,
            "authenticated": False,
            "target_url": target_url,
            "reason": "probe_exception",
            "error": safe_exception_text(exc),
        }


def _build_cdp_unreachable_auth_probe(config: SeedCollectorConfig, target_url: str) -> dict[str, Any]:
    from tools import taobao_login_health
    from tools.safe_exception_diagnostics import safe_cdp_endpoint

    effective_target_url = str(target_url or "").strip() or "https://sf.taobao.com/list/50025969__2.htm"
    endpoint = safe_cdp_endpoint(config.cdp_endpoint)
    hint = taobao_login_health.build_operator_hint(
        status=taobao_login_health.CDP_UNREACHABLE,
        cdp_endpoint=endpoint,
        check_url=effective_target_url,
    )
    redacted = str(config.cdp_endpoint).strip().rstrip("/") != endpoint
    if redacted:
        hint["message"] += " Connection parameters were omitted; use the configured CDP endpoint locally."
    return {
        "attempted": True,
        "authenticated": False,
        "status": taobao_login_health.CDP_UNREACHABLE,
        "cdp_endpoint": endpoint,
        "cdp_endpoint_redacted": redacted,
        "target_url": effective_target_url,
        "operator_hint": hint,
    }


__all__ = (
    '_extract_seed_items',
    '_browser_page_payload_missing_without_challenge',
    '_write_runtime_summary',
    '_collection_pause_state',
    '_normalize_collection_pause_state',
    '_captcha_solver_targets_current_node',
    '_collection_pause_state_with_retry',
    '_pause_state_targets_detail_page',
    '_default_seed_auth_probe_target_url',
    '_normalize_seed_challenge_target_url',
    '_pause_state_seed_probe_target_url',
    '_pause_state_blocks_seed_stage',
    '_notify_auth_probe_passed',
    '_probe_seed_auth_state',
    '_build_cdp_unreachable_auth_probe',
)
