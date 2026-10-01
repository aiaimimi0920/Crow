from __future__ import annotations
from tools.live_smoke_context import *  # noqa: F401,F403
from tools.live_smoke_resume import *  # noqa: F401,F403
from tools.live_smoke_list import *  # noqa: F401,F403
from tools.live_smoke_area import *  # noqa: F401,F403


def is_challenge_page(html: str, final_url: str) -> bool:
    browserless_seed_probe = _browserless_seed_probe()
    summary = browserless_seed_probe.summarize_list_page(html, final_url=final_url)
    if summary.get("body_has_challenge") or summary.get("body_has_login"):
        return True
    text = html or ""
    lowered_final_url = str(final_url or "").lower()
    return "challenge" in lowered_final_url or any(
        marker in text for marker in ("霸下通用 web 页面-验证码", "_____tmd_____/punish", "x5secdata=")
    )

def is_login_page(html: str, final_url: str) -> bool:
    browserless_seed_probe = _browserless_seed_probe()
    summary = browserless_seed_probe.summarize_list_page(html, final_url=final_url)
    lowered_final_url = str(final_url or "").lower()
    return bool(summary.get("body_has_login")) or any(
        marker in lowered_final_url
        for marker in ("login.taobao.com", "login.m.taobao.com", "havanaone/login")
    )

def _configured_cookie_snapshot_path() -> Path | None:
    explicit = (project_getenv("CROW_COOKIE_SNAPSHOT") or "").strip()
    if explicit:
        return Path(explicit)
    shared_root = (
        (project_getenv("CROW_SHARED_DATA_ROOT_HOST") or "").strip()
        or (str(resolve_project_data_root(REPO_ROOT)) if any(
            str(os.getenv(key) or "").strip()
            for key in ("CROW_DATA_ROOT_HOST", "FAPAI_DATA_ROOT_HOST")
        ) else "")
    )
    node_id = (project_getenv("CROW_NODE_ID") or "").strip()
    if not shared_root or not node_id:
        return None
    return Path(shared_root) / "secrets" / "nodes" / node_id / "taobao-cookies.json"

def _write_cookie_snapshot_best_effort(browserless_seed_probe: Any, cookies: list[dict[str, Any]], snapshot_path: Path | None) -> None:
    if snapshot_path is None:
        return
    try:
        browserless_seed_probe.write_cookie_snapshot(cookies, snapshot_path)
    except Exception:
        return

def export_cookies(cdp_endpoint: str) -> list[dict[str, Any]]:
    browserless_seed_probe = _browserless_seed_probe()
    snapshot = _configured_cookie_snapshot_path()
    prefer_snapshot = (project_getenv("CROW_COOKIE_SNAPSHOT_PREFER") or "").strip().lower() in TRUE_VALUES
    if prefer_snapshot and snapshot is not None:
        try:
            return browserless_seed_probe.load_cookie_snapshot(snapshot)
        except FileNotFoundError:
            cookies = browserless_seed_probe.export_cdp_cookies(cdp_endpoint)
            _write_cookie_snapshot_best_effort(browserless_seed_probe, cookies, snapshot)
            return cookies
    try:
        cookies = browserless_seed_probe.export_cdp_cookies(cdp_endpoint)
        _write_cookie_snapshot_best_effort(browserless_seed_probe, cookies, snapshot)
        return cookies
    except EnvironmentAliasConflict:
        raise
    except Exception as export_exc:
        if snapshot is None:
            raise
        try:
            return browserless_seed_probe.load_cookie_snapshot(snapshot)
        except Exception as snapshot_exc:
            raise RuntimeError(
                f"cdp cookie export failed: {export_exc!r}; "
                f"snapshot fallback failed: {snapshot_exc!r}"
            ) from snapshot_exc

def list_browser_fallback_enabled() -> bool:
    raw = project_getenv("CROW_LIST_BROWSER_FALLBACK")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}

def detail_browser_fallback_enabled() -> bool:
    raw = project_getenv("CROW_DETAIL_BROWSER_FALLBACK")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}

def captcha_solver_enabled(*, default: bool = False) -> bool:
    for name in CAPTCHA_SOLVER_ENV_NAMES:
        raw = project_getenv(name)
        if raw is None:
            continue
        text = raw.strip()
        if text:
            return text.lower() in TRUE_VALUES
    return default

def _positive_int_env(name: str, default: int) -> int:
    raw = project_getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default

def _positive_float_env(name: str, default: float) -> float:
    raw = project_getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = float(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default

def detail_browser_ready_timeout_ms() -> int:
    return _positive_int_env(
        "CROW_DETAIL_BROWSER_READY_TIMEOUT_MS",
        DEFAULT_DETAIL_BROWSER_READY_TIMEOUT_MS,
    )

def detail_browser_poll_interval_ms() -> int:
    return _positive_int_env(
        "CROW_DETAIL_BROWSER_POLL_INTERVAL_MS",
        DEFAULT_DETAIL_BROWSER_POLL_INTERVAL_MS,
    )

def _detail_page_has_ready_marker(html: str) -> bool:
    lowered = str(html or "").lower()
    return any(
        marker in lowered
        for marker in (
            'id="j_startprice',
            "id='j_startprice",
            'id="itemaddress',
            "id='itemaddress",
            'id="description-data',
            "id='description-data",
            'class="countdown',
            "class='countdown",
        )
    )

def _wait_for_detail_ready(
    page: Any,
    *,
    timeout_ms: int | None = None,
    poll_interval_ms: int | None = None,
) -> str:
    """Poll detail DOM readiness while preserving immediate challenge detection."""
    timeout = max(int(timeout_ms or detail_browser_ready_timeout_ms()), 1)
    poll_interval = max(int(poll_interval_ms or detail_browser_poll_interval_ms()), 1)
    deadline = time.monotonic() + timeout / 1000.0
    max_polls = max((timeout + poll_interval - 1) // poll_interval, 1)
    last_html = ""
    for poll_index in range(max_polls + 1):
        last_html = read_page_content_with_retries(page, attempts=1)
        final_url = str(getattr(page, "url", "") or "")
        if is_challenge_page(last_html, final_url) or _detail_page_has_ready_marker(last_html):
            return last_html
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if poll_index >= max_polls or remaining_ms <= 0:
            break
        page.wait_for_timeout(min(poll_interval, max(1, remaining_ms)))
    return last_html

def list_browser_recovery_max_attempts() -> int:
    return _positive_int_env(
        "CROW_LIST_BROWSER_RECOVERY_MAX_ATTEMPTS",
        DEFAULT_LIST_BROWSER_RECOVERY_MAX_ATTEMPTS,
    )

def list_browser_recovery_wait_seconds() -> float:
    return _positive_float_env(
        "CROW_LIST_BROWSER_RECOVERY_WAIT_SECONDS",
        DEFAULT_LIST_BROWSER_RECOVERY_WAIT_SECONDS,
    )

def list_http_timeout_seconds() -> float:
    return _positive_float_env(
        "CROW_LIST_HTTP_TIMEOUT_SECONDS",
        40.0,
    )

def build_http(cookies: list[dict[str, Any]]) -> requests.Session:
    browserless_seed_probe = _browserless_seed_probe()
    session = browserless_seed_probe.build_session_from_playwright_cookies(cookies)
    session.trust_env = False
    explicit_proxy = project_getenv("CROW_HTTP_PROXY") or project_getenv("CROW_PROXY")
    explicit_https_proxy = project_getenv("CROW_HTTPS_PROXY") or explicit_proxy
    session.proxies = {
        "http": explicit_proxy,
        "https": explicit_https_proxy,
    }
    return session

def resolve_runtime_user_agent(cdp_endpoint: str) -> str:
    browserless_seed_probe = _browserless_seed_probe()
    resolver = getattr(browserless_seed_probe, "resolve_cdp_user_agent", None)
    if callable(resolver):
        try:
            return str(resolver(cdp_endpoint, default=getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT)) or "")
        except Exception:
            pass
    return getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT)

def build_navigation_headers(*, target_url: str, user_agent: str, referer_url: str) -> dict[str, str]:
    browserless_seed_probe = _browserless_seed_probe()
    builder = getattr(browserless_seed_probe, "build_navigation_headers", None)
    if callable(builder):
        try:
            return dict(
                builder(
                    target_url=target_url,
                    user_agent=user_agent,
                    referer_url=referer_url,
                )
            )
        except Exception:
            pass
    return {
        "User-Agent": str(user_agent or getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT)),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "max-age=0",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-site" if str(referer_url or "").strip() else "none",
        "Sec-Fetch-User": "?1",
        "Referer": str(referer_url or ""),
    }

def _default_list_referer_url(target_url: str) -> str:
    normalized_target = str(target_url or "").strip()
    if not normalized_target:
        return "https://sf.taobao.com/"
    try:
        parsed = urlparse(normalized_target)
    except ValueError:
        return "https://sf.taobao.com/"
    hostname = str(parsed.hostname or "").lower()
    if hostname != "sf.taobao.com":
        return "https://sf.taobao.com/"
    if "/list/" not in str(parsed.path or "").lower():
        return "https://sf.taobao.com/"
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.pop("__captcha_solver_bg", None)
    page_values = query.get("page") or []
    try:
        current_page = int(page_values[-1]) if page_values else 1
    except (TypeError, ValueError):
        current_page = 1
    if current_page <= 1:
        return "https://sf.taobao.com/"
    query["page"] = [str(current_page - 1)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

def _cdp_page_target_limit() -> int:
    raw = project_getenv("CROW_CDP_MAX_PAGE_TARGETS")
    if raw is None or not raw.strip():
        return DEFAULT_CDP_PAGE_TARGET_LIMIT
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_CDP_PAGE_TARGET_LIMIT
    return parsed if parsed > 0 else DEFAULT_CDP_PAGE_TARGET_LIMIT

def _cdp_url(cdp_endpoint: str, path: str) -> str:
    return f"{str(cdp_endpoint or '').rstrip('/')}/{path.lstrip('/')}"

def _cdp_http_get(cdp_endpoint: str, path: str, *, timeout_seconds: float) -> Any:
    session = requests.Session()
    session.trust_env = False
    return session.get(_cdp_url(cdp_endpoint, path), timeout=timeout_seconds)

def _cdp_http_put(cdp_endpoint: str, path: str, *, timeout_seconds: float) -> Any:
    session = requests.Session()
    session.trust_env = False
    return session.put(_cdp_url(cdp_endpoint, path), timeout=timeout_seconds)

def _fallback_cached_playwright_cdp_endpoint(cdp_endpoint: str) -> str:
    try:
        probe = _browserless_seed_probe()
    except Exception:
        return ""

    cached_loader = getattr(probe, "_load_cached_cdp_websocket", None)
    if callable(cached_loader):
        try:
            cached = str(cached_loader(cdp_endpoint) or "").strip()
        except EnvironmentAliasConflict:
            raise
        except Exception:
            cached = ""
        if cached.startswith(("ws://", "wss://")):
            return cached

    resolver = getattr(probe, "_resolve_cdp_endpoint", None)
    if callable(resolver):
        try:
            resolved = str(resolver(cdp_endpoint) or "").strip()
        except EnvironmentAliasConflict:
            raise
        except Exception:
            resolved = ""
        if resolved.startswith(("ws://", "wss://")):
            return resolved

    return ""

__all__ = ('is_challenge_page', 'is_login_page', '_configured_cookie_snapshot_path', '_write_cookie_snapshot_best_effort', 'export_cookies', 'list_browser_fallback_enabled', 'detail_browser_fallback_enabled', 'captcha_solver_enabled', '_positive_int_env', '_positive_float_env', 'detail_browser_ready_timeout_ms', 'detail_browser_poll_interval_ms', '_detail_page_has_ready_marker', '_wait_for_detail_ready', 'list_browser_recovery_max_attempts', 'list_browser_recovery_wait_seconds', 'list_http_timeout_seconds', 'build_http', 'resolve_runtime_user_agent', 'build_navigation_headers', '_default_list_referer_url', '_cdp_page_target_limit', '_cdp_url', '_cdp_http_get', '_cdp_http_put', '_fallback_cached_playwright_cdp_endpoint')
