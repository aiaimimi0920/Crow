"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.taobao_health_context import *


def fetch_pages_via_cdp(cdp_endpoint: str, urls: Sequence[str]) -> list[tuple[str, str]]:
    from playwright.sync_api import sync_playwright

    results: list[tuple[str, str]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(resolve_playwright_cdp_endpoint(cdp_endpoint), timeout=DEFAULT_CDP_CONNECT_TIMEOUT_MS)
        try:
            if not browser.contexts:
                context = browser.new_context()
            else:
                context = browser.contexts[0]
            for url in urls:
                page = context.new_page()
                try:
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    except Exception:
                        # Taobao punish/challenge navigations can stay pending; classify current DOM anyway.
                        pass
                    results.append((read_page_content_with_retries(page), page.url))
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
        finally:
            detach_attached_cdp_browser(browser)
    return results


def fetch_page_via_cdp(cdp_endpoint: str, url: str) -> tuple[str, str]:
    return fetch_pages_via_cdp(cdp_endpoint, (url,))[0]


def fetch_health_samples_via_cdp_cookie_http(cdp_endpoint: str, urls: Sequence[str]) -> list[dict[str, object]]:
    from tools import browserless_seed_probe

    cookies = browserless_seed_probe._export_cdp_cookies_via_websocket(
        cdp_endpoint,
        browserless_seed_probe.DEFAULT_COOKIE_ORIGINS,
    )
    cookie_summary = dict(browserless_seed_probe.summarize_cookie_snapshot(cookies))
    cookie_summary.pop("names", None)
    session = browserless_seed_probe.build_session_from_playwright_cookies(cookies)
    results: list[dict[str, object]] = []
    for url in urls:
        summary = browserless_seed_probe.probe_seed_page(url, cookies=cookies, session=session)
        final_url = str(summary.get("final_url") or url)
        list_summary = {
            "has_script": summary.get("has_script"),
            "item_count": summary.get("item_count"),
            "first_ids": summary.get("first_ids"),
            "first_urls": summary.get("first_urls"),
            "body_has_login": summary.get("body_has_login"),
            "body_has_captcha": summary.get("body_has_captcha"),
            "body_has_punish": summary.get("body_has_punish"),
            "body_has_challenge": summary.get("body_has_challenge"),
            "body_snippet": summary.get("body_snippet"),
        }
        results.append(
            _build_taobao_health_result_from_summary(
                cdp_endpoint=cdp_endpoint,
                check_url=str(url),
                final_url=final_url,
                list_summary=list_summary,
                payload_present=summary.get("has_script") is True,
                probe_transport="cookie_http",
                cookie_summary=cookie_summary,
            )
        )
    return results


def build_cdp_verification_page_matcher(url: str) -> Callable[[str], bool]:
    from urllib.parse import parse_qs

    from src.collection.adapters.taobao_solver_target import (
        _is_taobao_login_target,
        _is_taobao_target,
        _solver_request_scope_from_target_url,
        _split_web_target_url,
    )
    from tools.taobao_health_captcha import _captcha_solver_route

    requested = _split_web_target_url(url)
    if requested is None:
        return lambda _candidate_url: False
    requested_query = parse_qs(requested.query, keep_blank_values=True)
    requested_worker_master = requested_query.get("__captcha_worker_master") == ["1"]
    requested_solver_target = requested_query.get("__captcha_solver_bg") == ["1"]
    requested_route = _captcha_solver_route(url)
    requested_scope = _solver_request_scope_from_target_url(url)
    requested_taobao = _is_taobao_target(requested)
    requested_login = _is_taobao_login_target(requested)

    def is_taobao_verification_page(candidate_url: str) -> bool:
        candidate = _split_web_target_url(candidate_url)
        if candidate is None:
            return False
        query = parse_qs(candidate.query, keep_blank_values=True)
        candidate_route = _captcha_solver_route(candidate_url)
        if requested_worker_master:
            return (
                query.get("__captcha_worker_master") == ["1"]
                and candidate_route == requested_route
            )
        candidate_login = _is_taobao_login_target(candidate)
        if requested_login:
            return candidate_login
        candidate_solver = query.get("__captcha_solver_bg") == ["1"] or query.get(
            "__captcha_manual_popup"
        ) == ["1"]
        path_segments = {segment.lower() for segment in candidate.path.split("/")}
        candidate_challenge = bool(
            path_segments & {"_____tmd_____", "punish", "challenge"}
            or "x5secdata" in query
            or "x5step" in query
        )
        if requested_solver_target:
            # Login redirects do not retain the solver marker at the top level.
            # Only verified Taobao/Tmall targets may share this operator tab.
            if requested_taobao and candidate_login:
                return True
            if not (candidate_solver or candidate_challenge):
                return False
            if requested_scope != "unknown":
                return (
                    _solver_request_scope_from_target_url(candidate_url)
                    == requested_scope
                )
            # Keep explicitly requested local/test targets usable without
            # granting another origin access merely because it has a marker.
            return candidate_route == requested_route
        allowed_target = (
            _is_taobao_target(candidate)
            if requested_taobao
            else candidate_route == requested_route
        )
        return allowed_target and (
            candidate_login or candidate_solver or candidate_challenge
        )

    return is_taobao_verification_page


def _rewrite_cdp_payload_websockets(cdp_endpoint: str, payload: object) -> object:
    from tools import browserless_seed_probe

    if isinstance(payload, Mapping):
        rewritten = {
            str(key): _rewrite_cdp_payload_websockets(cdp_endpoint, value)
            for key, value in payload.items()
        }
        websocket_url = rewritten.get("webSocketDebuggerUrl")
        if isinstance(websocket_url, str):
            rewritten["webSocketDebuggerUrl"] = browserless_seed_probe.rewrite_cdp_websocket_url(
                cdp_endpoint,
                websocket_url,
            )
        return rewritten
    if isinstance(payload, list):
        return [_rewrite_cdp_payload_websockets(cdp_endpoint, item) for item in payload]
    return payload


def read_cdp_json(cdp_endpoint: str, path: str, *, method: str = "GET", timeout: int = 5) -> object:
    request = Request(cdp_endpoint.rstrip("/") + path, method=method)
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    if not body.strip():
        return {}
    return _rewrite_cdp_payload_websockets(cdp_endpoint, json.loads(body))


def list_cdp_targets(cdp_endpoint: str) -> list[Mapping[str, object]]:
    targets = read_cdp_json(cdp_endpoint, "/json/list")
    if isinstance(targets, Mapping):
        return [targets]
    if isinstance(targets, list):
        return [target for target in targets if isinstance(target, Mapping)]
    return []


def cdp_page_target_limit() -> int:
    raw_limit = project_getenv("CROW_CDP_MAX_PAGE_TARGETS", str(DEFAULT_CDP_PAGE_TARGET_LIMIT)).strip()
    try:
        limit = int(raw_limit)
    except ValueError:
        return DEFAULT_CDP_PAGE_TARGET_LIMIT
    return limit if limit > 0 else DEFAULT_CDP_PAGE_TARGET_LIMIT


def close_cdp_target(cdp_endpoint: str, target_id: object) -> bool:
    safe_target_id = str(target_id or "").strip()
    if not safe_target_id:
        return False
    request = Request(cdp_endpoint.rstrip("/") + f"/json/close/{quote(safe_target_id, safe='')}", method="GET")
    with urlopen(request, timeout=5) as response:
        response.read()
    return True


def open_cdp_keepalive_tab(cdp_endpoint: str) -> str:
    opened = read_cdp_json(cdp_endpoint, "/json/new?about:blank", method="PUT")
    if isinstance(opened, Mapping):
        return str(opened.get("id") or "")
    return ""


def compact_cdp_pages_if_needed(
    cdp_endpoint: str,
    targets: Sequence[Mapping[str, object]] | None = None,
    *,
    reserve_for_new_page: bool = False,
) -> Mapping[str, object]:
    targets = list(targets) if targets is not None else list_cdp_targets(cdp_endpoint)
    page_targets = [target for target in targets if str(target.get("type") or "") == "page"]
    target_limit = cdp_page_target_limit()
    trigger_count = max(target_limit - 1, 1) if reserve_for_new_page else target_limit
    if len(page_targets) < trigger_count:
        return {"triggered": False, "page_count": len(page_targets), "closed": 0}

    errors: list[str] = []
    keepalive_target_id = ""
    try:
        keepalive_target_id = open_cdp_keepalive_tab(cdp_endpoint)
    except Exception as error:
        errors.append(f"keepalive: {error!r}")
    preserve_target_id = keepalive_target_id or str(page_targets[0].get("id") or "").strip()
    closed = 0
    for target in page_targets:
        if str(target.get("id") or "").strip() == preserve_target_id:
            continue
        if close_cdp_target(cdp_endpoint, target.get("id")):
            closed += 1
    summary: dict[str, object] = {"triggered": True, "page_count": len(page_targets), "closed": closed}
    if keepalive_target_id:
        summary["keepalive_target_id"] = keepalive_target_id
    elif preserve_target_id:
        summary["preserved_target_id"] = preserve_target_id
    if errors:
        summary["errors"] = errors
    return summary


def activate_cdp_target(cdp_endpoint: str, target: Mapping[str, object]) -> None:
    target_id = str(target.get("id") or "")
    if not target_id:
        return
    request = Request(cdp_endpoint.rstrip("/") + f"/json/activate/{quote(target_id, safe='')}", method="GET")
    with urlopen(request, timeout=5) as response:
        response.read()


def find_cdp_target(cdp_endpoint: str, url: str) -> Mapping[str, object] | None:
    is_taobao_verification_page = build_cdp_verification_page_matcher(url)
    for target in list_cdp_targets(cdp_endpoint):
        candidate_url = str(target.get("url") or "")
        if is_taobao_verification_page(candidate_url):
            return target
    return None


__all__ = (
    'fetch_pages_via_cdp',
    'fetch_page_via_cdp',
    'fetch_health_samples_via_cdp_cookie_http',
    'build_cdp_verification_page_matcher',
    '_rewrite_cdp_payload_websockets',
    'read_cdp_json',
    'list_cdp_targets',
    'cdp_page_target_limit',
    'close_cdp_target',
    'open_cdp_keepalive_tab',
    'compact_cdp_pages_if_needed',
    'activate_cdp_target',
    'find_cdp_target',
)
