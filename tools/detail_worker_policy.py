"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.detail_worker_context import *


def _write_runtime_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "detail_worker_summary.json", summary)


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

    return _normalize_collection_pause_state(payload, scope="detail")


def _normalize_collection_pause_state(payload: dict[str, Any], scope: str = "detail") -> dict[str, Any]:
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
    solver_running_for_current_node = _captcha_solver_targets_current_node(captcha_solver)
    solver_running_only = (
        bool(payload.get("paused"))
        and bool(captcha_solver.get("running"))
        and bool(captcha_solver.get("paused"))
        and not manual_required
    )
    paused = bool(payload.get("paused")) or manual_required or solver_running_for_current_node
    if solver_running_only and not solver_running_for_current_node:
        paused = False
    reason = "captcha_solver_manual_required" if manual_required else "collection_paused" if paused else None
    if solver_running_for_current_node and not manual_required:
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


def _pause_state_detail_target_item_id(pause_state: dict[str, Any]) -> str | None:
    captcha_solver = pause_state.get("captcha_solver")
    if not isinstance(captcha_solver, dict):
        return None
    last_request = captcha_solver.get("last_request")
    if not isinstance(last_request, dict):
        return None
    target_url = str(last_request.get("target_url") or last_request.get("url") or "").strip()
    if not target_url:
        return None
    match = DETAIL_ITEM_ID_RE.search(target_url)
    if match is None:
        return None
    return str(match.group(1) or "").strip() or None


def _pause_state_has_resolved_open_detail_page(
    pause_state: dict[str, Any],
    browser_pages: dict[str, tuple[str, str]],
) -> bool:
    item_id = _pause_state_detail_target_item_id(pause_state)
    if not item_id:
        return False
    browser_page = browser_pages.get(item_id)
    if not browser_page:
        return False
    html, final_url = browser_page
    return bool(html) and not is_challenge_page(str(html), str(final_url))


def _is_detail_challenge_error(exc: BaseException) -> bool:
    text = repr(exc.cause if isinstance(exc, CdpEndpointUnavailableError) else exc).lower()
    return any(
        marker in text
        for marker in (
            "anti-bot challenge",
            "captcha",
            "punish",
            "x5secdata",
            "rgv587",
            "验证码",
            "security verification",
        )
    )


def _is_transient_dns_error(exc: BaseException) -> bool:
    text = repr(exc.cause if isinstance(exc, CdpEndpointUnavailableError) else exc).lower()
    return any(
        marker in text
        for marker in (
            "nameresolutionerror",
            "temporary failure in name resolution",
            "failed to resolve",
            "name or service not known",
            "getaddrinfo failed",
            "no address associated with hostname",
            "nodename nor servname provided",
        )
    )


def _is_llm_backend_unavailable_error(exc: BaseException) -> bool:
    from src import llm_helper

    if isinstance(exc, llm_helper.LLMBackendUnavailableError):
        return True
    text = repr(exc.cause if isinstance(exc, CdpEndpointUnavailableError) else exc).lower()
    return any(
        marker in text
        for marker in (
            "llm backend unavailable",
            "appidnoautherror",
            "empty response from ai",
            "all configured models are disabled",
        )
    )


def _report_captcha_solver(
    api_base_url: str,
    cdp_endpoint: str,
    target_url: str,
    *,
    manual_only: bool = False,
) -> dict[str, Any]:
    from tools.taobao_login_health import build_captcha_solver_target_url, report_captcha_via_api

    normalized_target_url = build_captcha_solver_target_url(target_url)
    report_kwargs: dict[str, Any] = {"scope": "detail"}
    if manual_only:
        report_kwargs["manual_only"] = True
    return dict(report_captcha_via_api(api_base_url, cdp_endpoint, normalized_target_url, **report_kwargs))


def _detail_seed_target_url(
    seed: dict[str, Any],
    item_id: str,
    *,
    adapter: CollectionAdapter | None = None,
) -> str:
    """Return a canonical detail URL; list provenance must never own detail challenge state."""
    active_adapter = resolve_record_adapter(seed, configured=adapter)
    source_item_id = str(seed.get("source_item_id") or seed.get("id") or item_id)
    for key in ("url", "source_url"):
        candidate = str(seed.get(key) or "").strip()
        if candidate and (
            active_adapter.source_platform != "taobao_sf"
            or DETAIL_ITEM_ID_RE.search(candidate)
        ):
            return active_adapter.seed_scan_policy.item_url(source_item_id, candidate)
    return active_adapter.seed_scan_policy.item_url(source_item_id)


def _challenge_retry_budget_preserved(*, is_challenge_error: bool, is_transient_dns: bool) -> bool:
    return bool(is_challenge_error or is_transient_dns)


def _captcha_report_suppresses_challenge(report: Any) -> bool:
    if not isinstance(report, dict):
        return False
    status = str(report.get("status") or "").strip().lower()
    return status in {
        "recent_auth_complete",
        "recent_force_reset",
        "stale_auth_report",
        "stale_challenge",
    }


def _detail_challenge_should_break_batch(_config: DetailWorkerConfig, result: dict[str, Any]) -> bool:
    if result.get("decision") != "detail_item_retryable_failure":
        return False
    if result.get("reason") == "detail_cdp_unreachable":
        return True
    return result.get("reason") in {
        "detail_challenge_page",
        "detail_stale_challenge_ignored",
    }


def _detail_challenge_retry_after_seconds(
    config: DetailWorkerConfig,
    result: dict[str, Any],
) -> int:
    if not _detail_challenge_should_break_batch(config, result):
        return 0
    retry_after = max(int(config.challenge_cooldown_seconds), 0)
    report = result.get("captcha_solver_report")
    if isinstance(report, dict):
        try:
            retry_after = max(
                retry_after,
                int(math.ceil(max(float(report.get("retry_after_seconds") or 0), 0.0))),
            )
        except (TypeError, ValueError):
            pass
    return retry_after


def _env_bool(name: str, default: bool = False) -> bool:
    raw = project_getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _build_cdp_unreachable_health(config: DetailWorkerConfig, target_url: str) -> dict[str, Any]:
    from tools import taobao_login_health
    from tools.safe_exception_diagnostics import safe_cdp_endpoint

    effective_target_url = str(target_url or "").strip()
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
        "status": taobao_login_health.CDP_UNREACHABLE,
        "cdp_endpoint": endpoint,
        "cdp_endpoint_redacted": redacted,
        "target_url": effective_target_url,
        "operator_hint": hint,
    }


__all__ = (
    '_write_runtime_summary',
    '_collection_pause_state',
    '_normalize_collection_pause_state',
    '_captcha_solver_targets_current_node',
    '_collection_pause_state_with_retry',
    '_pause_state_detail_target_item_id',
    '_pause_state_has_resolved_open_detail_page',
    '_is_detail_challenge_error',
    '_is_transient_dns_error',
    '_is_llm_backend_unavailable_error',
    '_report_captcha_solver',
    '_detail_seed_target_url',
    '_challenge_retry_budget_preserved',
    '_captcha_report_suppresses_challenge',
    '_detail_challenge_should_break_batch',
    '_detail_challenge_retry_after_seconds',
    '_env_bool',
    '_build_cdp_unreachable_health',
)
