from __future__ import annotations
from tools.live_smoke_context import *  # noqa: F401,F403
from tools.live_smoke_resume import *  # noqa: F401,F403
from tools.live_smoke_list import *  # noqa: F401,F403
from tools.live_smoke_area import *  # noqa: F401,F403
from tools.live_smoke_auth import *  # noqa: F401,F403


def resolve_playwright_cdp_endpoint(
    cdp_endpoint: str,
    *,
    timeout_seconds: float = DEFAULT_CDP_HTTP_TIMEOUT_SECONDS,
) -> str:
    normalized = str(cdp_endpoint or "").strip()
    if not normalized:
        return normalized
    if normalized.startswith(("ws://", "wss://")):
        return normalized
    try:
        response = _cdp_http_get(normalized, "/json/version", timeout_seconds=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return _fallback_cached_playwright_cdp_endpoint(normalized) or normalized
    if not isinstance(payload, dict):
        return _fallback_cached_playwright_cdp_endpoint(normalized) or normalized
    websocket_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
    if not websocket_url:
        return normalized
    try:
        rewrite = getattr(_browserless_seed_probe(), "rewrite_cdp_websocket_url", None)
    except Exception:
        rewrite = None
    return str(rewrite(normalized, websocket_url) if callable(rewrite) else websocket_url)

def open_cdp_keepalive_target(
    cdp_endpoint: str,
    *,
    timeout_seconds: float = DEFAULT_CDP_HTTP_TIMEOUT_SECONDS,
) -> str:
    response = _cdp_http_put(cdp_endpoint, "/json/new?about:blank", timeout_seconds=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("id") or "").strip()

def compact_cdp_page_targets_if_needed(
    cdp_endpoint: str,
    *,
    limit: int | None = None,
    timeout_seconds: float = DEFAULT_CDP_HTTP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    effective_limit = int(limit or _cdp_page_target_limit())
    summary: dict[str, Any] = {"triggered": False, "page_count": 0, "closed": 0, "errors": []}
    if not str(cdp_endpoint or "").strip() or effective_limit <= 0:
        return summary
    try:
        response = _cdp_http_get(cdp_endpoint, "/json/list", timeout_seconds=timeout_seconds)
        response.raise_for_status()
        targets = response.json()
    except Exception as error:
        summary["errors"].append(safe_exception_text(error))
        return summary
    if not isinstance(targets, list):
        summary["errors"].append("CDP /json/list response is not a list")
        return summary
    page_targets = [
        target
        for target in targets
        if isinstance(target, dict) and str(target.get("type") or "").lower() == "page"
    ]
    summary["page_count"] = len(page_targets)
    if len(page_targets) < effective_limit:
        return summary
    summary["triggered"] = True
    keepalive_target_id = ""
    try:
        keepalive_target_id = open_cdp_keepalive_target(cdp_endpoint, timeout_seconds=timeout_seconds)
    except Exception as error:
        summary["errors"].append(f"keepalive: {safe_exception_text(error)}")
    if keepalive_target_id:
        summary["keepalive_target_id"] = keepalive_target_id
    preserve_target_id = keepalive_target_id or str(page_targets[0].get("id") or "").strip()
    if preserve_target_id and not keepalive_target_id:
        summary["preserved_target_id"] = preserve_target_id
    for target in page_targets:
        target_id = str(target.get("id") or "").strip()
        if not target_id:
            continue
        if target_id == preserve_target_id:
            continue
        try:
            close_response = _cdp_http_get(
                cdp_endpoint,
                f"/json/close/{quote(target_id, safe='')}",
                timeout_seconds=timeout_seconds,
            )
            close_response.raise_for_status()
            summary["closed"] += 1
        except Exception as error:
            summary["errors"].append(f"{target_id}: {safe_exception_text(error)}")
    return summary

def _cdp_reconnect_attempts() -> int:
    raw = project_getenv("CROW_CDP_RECONNECT_ATTEMPTS", str(DEFAULT_CDP_RECONNECT_ATTEMPTS))
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = DEFAULT_CDP_RECONNECT_ATTEMPTS
    return max(1, min(value, 10))

def _cdp_reconnect_backoff_seconds() -> float:
    raw = project_getenv("CROW_CDP_RECONNECT_BACKOFF_SECONDS", str(DEFAULT_CDP_RECONNECT_BACKOFF_SECONDS))
    try:
        value = float(str(raw or "").strip())
    except ValueError:
        value = DEFAULT_CDP_RECONNECT_BACKOFF_SECONDS
    return max(0.0, min(value, 30.0))

def _cdp_endpoint_healthy_for_reconnect(cdp_endpoint: str) -> bool:
    try:
        probe = _browserless_seed_probe()
        health_check = getattr(probe, "cdp_endpoint_is_healthy", None)
        if callable(health_check):
            return bool(health_check(cdp_endpoint, timeout_seconds=DEFAULT_CDP_HTTP_TIMEOUT_SECONDS))
    except EnvironmentAliasConflict:
        raise
    except Exception:
        return False
    return bool(resolve_playwright_cdp_endpoint(cdp_endpoint))

def connect_browser_over_cdp(playwright: Any, cdp_endpoint: str, *, timeout_ms: int = DEFAULT_CDP_CONNECT_TIMEOUT_MS) -> Any:
    attempts = _cdp_reconnect_attempts()
    backoff = _cdp_reconnect_backoff_seconds()
    try:
        compaction = compact_cdp_page_targets_if_needed(cdp_endpoint)
    except EnvironmentAliasConflict:
        raise
    except Exception as error:
        _raise_cdp_endpoint_unavailable(cdp_endpoint, "compact_cdp_page_targets", error)
    if compaction.get("triggered"):
        print(json.dumps({"event": "cdp_page_target_compaction", **compaction}, ensure_ascii=False))
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        if attempt > 1 and not _cdp_endpoint_healthy_for_reconnect(cdp_endpoint):
            last_error = RuntimeError(f"CDP health check failed before reconnect attempt {attempt}")
            if attempt < attempts and backoff > 0:
                time.sleep(backoff * attempt)
            continue
        try:
            resolved_endpoint = resolve_playwright_cdp_endpoint(cdp_endpoint)
            return playwright.chromium.connect_over_cdp(resolved_endpoint, timeout=timeout_ms)
        except EnvironmentAliasConflict:
            raise
        except Exception as error:
            last_error = error
        if attempt < attempts and backoff > 0:
            time.sleep(backoff * attempt)
    _raise_cdp_endpoint_unavailable(
        cdp_endpoint,
        "connect_over_cdp_bounded_reconnect",
        last_error or RuntimeError("CDP connection failed without an explicit error"),
    )

def detach_attached_cdp_browser(browser: Any) -> None:
    """Detach from an externally managed CDP browser without closing the host process."""
    disconnect = getattr(browser, "disconnect", None)
    if callable(disconnect):
        try:
            disconnect()
        except Exception:
            pass

def _browser_identity_values(cdp_endpoint: str) -> tuple[str, str]:
    """Resolve the Windows UA identity shared by PC2 workers and the solver."""
    from tools.cdp_browser_identity import _chrome_full_version

    user_agent = str(project_getenv("CROW_BROWSER_USER_AGENT") or "").strip()
    full_version = str(project_getenv("CROW_BROWSER_IDENTITY_FULL_VERSION") or "").strip()
    browser_product = ""
    if not user_agent or not full_version:
        response = _cdp_http_get(
            cdp_endpoint,
            "/json/version",
            timeout_seconds=DEFAULT_CDP_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("CDP version response is not an object")
        browser_product = str(payload.get("Browser") or "").strip()
    if not full_version:
        full_version = _chrome_full_version(browser_product)
    if not user_agent:
        major = str(full_version or "").split(".", 1)[0]
        if not major.isdigit():
            raise RuntimeError("unable to derive Chrome major version for browser identity")
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36"
        )
    if not full_version:
        raise RuntimeError("unable to resolve Chrome full version for browser identity")
    return user_agent, full_version

def configure_browser_identity_before_navigation(
    context: Any,
    page: Any,
    *,
    cdp_endpoint: str,
) -> dict[str, Any]:
    """Install and verify the solver identity before the first remote request."""
    from tools.cdp_browser_identity import browser_identity_init_script, build_user_agent_override

    user_agent, full_version = _browser_identity_values(cdp_endpoint)
    source = browser_identity_init_script()
    session = context.new_cdp_session(page)
    try:
        session.send(
            "Emulation.setUserAgentOverride",
            build_user_agent_override(user_agent, full_version),
        )
        session.send("Emulation.setTimezoneOverride", {"timezoneId": "Asia/Shanghai"})
        try:
            session.send("Emulation.setLocaleOverride", {"locale": "zh-CN"})
        except Exception as error:
            # The browser-wide identity controller may already own the locale
            # override. Chrome rejects a duplicate CDP owner even when it uses
            # the same locale, so verify the effective value below instead of
            # failing an otherwise coherent page.
            if "Another locale override is already in effect" not in str(error):
                raise
        session.send("Page.addScriptToEvaluateOnNewDocument", {"source": source})
        session.send(
            "Runtime.evaluate",
            {"expression": source, "returnByValue": True},
        )
        identity = page.evaluate(
            """() => ({
              userAgent: navigator.userAgent,
              platform: navigator.platform,
              uaPlatform: navigator.userAgentData ? navigator.userAgentData.platform : '',
              webdriver: navigator.webdriver,
              deviceMemory: navigator.deviceMemory,
              language: navigator.language
            })"""
        )
    finally:
        detach = getattr(session, "detach", None)
        if callable(detach):
            try:
                detach()
            except Exception:
                # The browser-wide auto-attach controller can reclaim this
                # temporary session first. Identity commands are already
                # applied; cleanup must not turn that success into a failed
                # navigation.
                pass
    if not isinstance(identity, dict):
        raise RuntimeError("browser identity preflight returned an invalid result")
    if (
        "Windows NT 10.0" not in str(identity.get("userAgent") or "")
        or str(identity.get("platform") or "") != "Win32"
        or str(identity.get("uaPlatform") or "") not in {"", "Windows"}
        or identity.get("webdriver") is not False
        or identity.get("deviceMemory") != 8
        or str(identity.get("language") or "") != "zh-CN"
    ):
        raise RuntimeError("browser identity preflight failed before navigation")
    return identity

def read_page_content_with_retries(
    page: Any,
    *,
    attempts: int = 5,
    wait_timeout_ms: int = 500,
) -> str:
    last_error: Exception | None = None
    for attempt_index in range(max(int(attempts), 1)):
        try:
            return str(page.content() or "")
        except Exception as error:
            last_error = error
            if attempt_index >= max(int(attempts), 1) - 1:
                break
            try:
                page.wait_for_timeout(wait_timeout_ms)
            except Exception:
                break
    if last_error is not None:
        raise last_error
    return ""

def request_captcha_solver(
    cdp_endpoint: str,
    target_url: str,
    *,
    api_base_url: str | None = None,
    manual_only: bool = False,
) -> dict[str, Any]:
    from tools.taobao_login_health import build_captcha_solver_target_url, report_captcha_via_api

    solver_target_url = build_captcha_solver_target_url(target_url)
    report_kwargs = {"manual_only": True} if manual_only else {}
    response = report_captcha_via_api(
        str(api_base_url or DEFAULT_API_BASE_URL),
        cdp_endpoint,
        solver_target_url,
        **report_kwargs,
    )
    return dict(response) if isinstance(response, dict) else {"status": "unknown_response", "raw": response}

def fetch_open_browser_pages(cdp_endpoint: str) -> dict[str, tuple[str, str]]:
    from playwright.sync_api import sync_playwright

    pages: dict[str, tuple[str, str]] = {}
    with sync_playwright() as p:
        browser = connect_browser_over_cdp(p, cdp_endpoint)
        try:
            for context in browser.contexts:
                for page in context.pages:
                    url = page.url or ""
                    if "/sf_item/" not in url:
                        continue
                    item_id = url.split("/sf_item/", 1)[1].split(".htm", 1)[0]
                    page.wait_for_timeout(1000)
                    pages[item_id] = (read_page_content_with_retries(page), url)
        finally:
            detach_attached_cdp_browser(browser)
    return pages

def load_open_browser_pages(cdp_endpoint: str) -> dict[str, tuple[str, str]]:
    try:
        return fetch_open_browser_pages(cdp_endpoint)
    except EnvironmentAliasConflict:
        raise
    except Exception:
        return {}

def _normalize_browser_match_url(
    url: str,
    *,
    drop_params: Iterable[str] = ("__captcha_solver_bg", "x5secdata", "x5step"),
) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    query = parse_qs(parsed.query, keep_blank_values=True)
    path = parsed.path or ""
    if "/_____tmd_____/punish" in path:
        path = path.split("/_____tmd_____/punish", 1)[0]
    while "//" in path:
        path = path.replace("//", "/")
    for param in drop_params:
        query.pop(str(param), None)
    normalized_query = urlencode(
        sorted((key, value) for key, values in query.items() for value in values),
        doseq=True,
    )
    return urlunparse(parsed._replace(path=path, query=normalized_query, fragment=""))

def _cdp_runtime_value(response: Mapping[str, Any] | dict[str, Any]) -> Any:
    if not isinstance(response, dict):
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    inner = result.get("result")
    if not isinstance(inner, dict):
        return None
    return inner.get("value")

def _raise_cdp_endpoint_unavailable(cdp_endpoint: str, operation: str, error: BaseException) -> None:
    if isinstance(error, CdpEndpointUnavailableError):
        raise error
    raise CdpEndpointUnavailableError(cdp_endpoint, operation, error) from error

def _read_cdp_list_target_html(
    cdp_endpoint: str,
    target: Mapping[str, Any] | dict[str, Any],
    *,
    polls: int = 5,
    wait_seconds: float = 1.0,
) -> tuple[str, str]:
    from tools import taobao_login_health

    taobao_login_health.activate_cdp_target(cdp_endpoint, target)
    websocket_url = str(target.get("webSocketDebuggerUrl") or "").strip()
    if not websocket_url:
        raise RuntimeError(f"CDP target missing webSocketDebuggerUrl: {target!r}")

    expression = (
        "(() => {"
        "return {"
        "html: document.documentElement ? document.documentElement.outerHTML : '',"
        "url: window.location.href || ''"
        "};"
        "})()"
    )
    last_html = ""
    last_url = str(target.get("url") or "").strip()
    for attempt_index in range(max(int(polls), 1)):
        response = taobao_login_health.evaluate_cdp_expression(websocket_url, expression)
        value = _cdp_runtime_value(response)
        if isinstance(value, dict):
            html = str(value.get("html") or "")
            url = str(value.get("url") or last_url or "")
        else:
            html = ""
            url = last_url
        if html:
            last_html = html
        if url:
            last_url = url
        if last_html and ("sf-item-list-data" in last_html or is_challenge_page(last_html, last_url)):
            break
        if attempt_index < max(int(polls), 1) - 1 and wait_seconds > 0:
            time.sleep(wait_seconds)
    return last_html, last_url

def _find_matching_cdp_list_targets(cdp_endpoint: str, target_url: str) -> list[dict[str, Any]]:
    from tools import taobao_login_health

    normalized_target = _normalize_browser_match_url(target_url)
    matches: list[dict[str, Any]] = []
    for target in taobao_login_health.list_cdp_targets(cdp_endpoint):
        if not isinstance(target, dict):
            continue
        if str(target.get("type") or "").lower() != "page":
            continue
        page_url = str(target.get("url") or "")
        if "/list/" not in page_url:
            continue
        if normalized_target and _normalize_browser_match_url(page_url) != normalized_target:
            continue
        matches.append(dict(target))
    return matches

def _is_taobao_login_target_url(value: str) -> bool:
    """Return whether a CDP page is the shared Taobao login surface.

    Login redirects include the requested auction URL in a query parameter, so
    matching only the requested list/detail URL misses the actual auth tab.
    Keep this matcher deliberately host/path based and scope-independent: list
    and detail collectors must share one operator login window.
    """
    lowered = str(value or "").strip().lower()
    return any(
        marker in lowered
        for marker in (
            "login.taobao.com",
            "login.m.taobao.com",
            "login.tmall.com",
            "havanaone/login",
        )
    )

__all__ = ('resolve_playwright_cdp_endpoint', 'open_cdp_keepalive_target', 'compact_cdp_page_targets_if_needed', '_cdp_reconnect_attempts', '_cdp_reconnect_backoff_seconds', '_cdp_endpoint_healthy_for_reconnect', 'connect_browser_over_cdp', 'detach_attached_cdp_browser', '_browser_identity_values', 'configure_browser_identity_before_navigation', 'read_page_content_with_retries', 'request_captcha_solver', 'fetch_open_browser_pages', 'load_open_browser_pages', '_normalize_browser_match_url', '_cdp_runtime_value', '_raise_cdp_endpoint_unavailable', '_read_cdp_list_target_html', '_find_matching_cdp_list_targets', '_is_taobao_login_target_url')
