from __future__ import annotations
from tools.live_smoke_context import *  # noqa: F401,F403
from tools.live_smoke_resume import *  # noqa: F401,F403
from tools.live_smoke_list import *  # noqa: F401,F403
from tools.live_smoke_area import *  # noqa: F401,F403
from tools.live_smoke_auth import *  # noqa: F401,F403
from tools.live_smoke_cdp import *  # noqa: F401,F403


def _reuse_existing_taobao_login_page(
    cdp_endpoint: str,
) -> tuple[str, str] | None:
    """Read one existing login tab and close competing login tabs.

    This runs before any ``/json/new`` navigation.  A challenge can redirect
    several workers to ``login.taobao.com``; opening a fresh tab for each retry
    invalidates the operator's QR/password session.  Reusing the first tab and
    pruning only duplicate login tabs preserves the single five-minute auth
    window without touching unrelated list/detail challenge pages.
    """
    from tools import taobao_login_health

    try:
        targets = list(taobao_login_health.list_cdp_targets(cdp_endpoint))
    except Exception:
        return None
    login_targets = [
        target
        for target in targets
        if isinstance(target, dict)
        and str(target.get("type") or "").lower() == "page"
        and _is_taobao_login_target_url(str(target.get("url") or ""))
    ]
    if not login_targets:
        return None
    selected = login_targets[0]
    selected_id = str(selected.get("id") or "").strip()
    for duplicate in login_targets[1:]:
        duplicate_id = str(duplicate.get("id") or "").strip()
        if duplicate_id and duplicate_id != selected_id:
            try:
                taobao_login_health.close_cdp_target(cdp_endpoint, duplicate_id)
            except Exception:
                pass
    try:
        taobao_login_health.activate_cdp_target(cdp_endpoint, selected)
        html, final_url = _read_cdp_list_target_html(cdp_endpoint, selected)
    except Exception:
        return None
    return html, final_url


def _reuse_existing_taobao_challenge_page(
    cdp_endpoint: str,
) -> tuple[str, str] | None:
    """Reuse an obvious Taobao challenge tab before opening another target."""
    from tools import taobao_login_health

    try:
        targets = list(taobao_login_health.list_cdp_targets(cdp_endpoint))
    except Exception:
        return None
    for target in targets:
        if not isinstance(target, dict) or str(target.get("type") or "").lower() != "page":
            continue
        target_url = str(target.get("url") or "")
        parsed = urlparse(target_url)
        host = (parsed.hostname or "").lower()
        obvious_challenge = _is_taobao_challenge_target_url(target_url)
        is_taobao_list = host == "sf.taobao.com" and "/list/" in (parsed.path or "")
        if not obvious_challenge and not is_taobao_list:
            continue
        try:
            html, final_url = _read_cdp_list_target_html(cdp_endpoint, target)
        except Exception:
            if obvious_challenge:
                return "", target_url
            continue
        if is_challenge_page(html, final_url):
            return html, final_url
    return None


def _is_taobao_challenge_target_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    host = (parsed.hostname or "").lower()
    is_taobao = bool(host and (host == "taobao.com" or host.endswith(".taobao.com")))
    return is_taobao and _list_final_url_has_challenge(value) and not _is_taobao_login_target_url(value)


def fetch_open_browser_list_page(
    cdp_endpoint: str,
    target_url: str,
    *,
    include_challenge: bool = False,
) -> tuple[str, str] | None:
    challenge_page: tuple[str, str] | None = None
    for target in _find_matching_cdp_list_targets(cdp_endpoint, target_url):
        html, page_url = _read_cdp_list_target_html(cdp_endpoint, target)
        if not html:
            continue
        if is_challenge_page(html, page_url):
            if include_challenge and challenge_page is None:
                challenge_page = (html, page_url)
            continue
        return html, page_url
    return challenge_page

def _read_text_if_exists(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return ""

def _redact_detail_analysis_text(text: str) -> str:
    sanitized = str(text or "")
    sanitized = CONTACT_FIELD_RE.sub(lambda match: f"{match.group(1)}: [REDACTED]", sanitized)
    sanitized = MOBILE_PHONE_RE.sub("[REDACTED_PHONE]", sanitized)
    sanitized = SERVICE_PHONE_RE.sub("[REDACTED_PHONE]", sanitized)
    sanitized = LANDLINE_PHONE_RE.sub("[REDACTED_PHONE]", sanitized)
    sanitized = EMAIL_RE.sub("[REDACTED_EMAIL]", sanitized)
    return sanitized

def _detail_input_value(soup: BeautifulSoup, element_id: str) -> str:
    node = soup.find(id=element_id)
    if node is None:
        return ""
    return str(node.get("value") or "").strip()

def _detail_node_text(soup: BeautifulSoup, element_id: str) -> str:
    node = soup.find(id=element_id)
    if node is None:
        return ""
    return node.get_text(" ", strip=True)

def _detail_countdown_text(soup: BeautifulSoup) -> str:
    node = soup.find(class_="countdown")
    if node is None:
        return ""
    return node.get_text(" ", strip=True)

def _build_detail_analysis_input(
    *,
    item_id: str,
    item_dir: Path,
    seed: dict[str, Any],
    html: str,
    selected: dict[str, Any],
    description_data: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    effective_seed = dict(seed)
    selected = as_dict(selected)
    trusted_seed = as_dict(selected.get("trusted_seed"))
    fetch = as_dict(selected.get("fetch"))
    final_core = as_dict(selected.get("final_core"))
    soup = BeautifulSoup(html or "", "html.parser")

    title = pick_first(
        final_core.get("title"),
        trusted_seed.get("title"),
        effective_seed.get("title"),
        soup.title.string.strip() if soup.title and soup.title.string else None,
    )
    final_url = pick_first(
        fetch.get("detail_final_url"),
        final_core.get("source_url"),
        effective_seed.get("url"),
        effective_seed.get("source_url"),
    )
    address = " ".join(
        part
        for part in (
            _detail_node_text(soup, "itemAddress"),
            _detail_node_text(soup, "itemAddressDetail"),
        )
        if part
    ).strip()
    page_end_time = _detail_countdown_text(soup)
    page_start_price = parse_positive_number(_detail_input_value(soup, "J_StartPrice"))
    page_status_code = _detail_input_value(soup, "J_Status")
    if page_start_price is not None:
        effective_seed["initialPrice"] = page_start_price
        effective_seed["起拍价格"] = page_start_price
    if address:
        effective_seed.setdefault("地点", address)
        effective_seed.setdefault("完整地址", address)

    description_text_path = Path(str(description_data.get("text_path") or item_dir / "description-data.txt"))
    description_text = _read_text_if_exists(description_text_path).strip()
    if not description_text and description_data:
        description_text = json.dumps(description_data, ensure_ascii=False, indent=2)

    lines = [
        "【可信种子】",
        f"id: {item_id}",
    ]
    if final_url:
        lines.append(f"url: {final_url}")
    if title:
        lines.append(f"title: {title}")
    for key in ("status", "currentPrice", "initialPrice", "auction_date", "bidCount", "applyCount"):
        value = pick_first(effective_seed.get(key), trusted_seed.get(key))
        if has_value(value):
            lines.append(f"{key}: {value}")

    lines.extend(["", "【详情页摘要】"])
    if address:
        lines.append(f"address: {address}")
    if page_end_time:
        lines.append(f"auction_end_time: {page_end_time}")
    if page_start_price is not None:
        lines.append(f"起拍价_html: {page_start_price}")
    if page_status_code:
        lines.append(f"status_code_html: {page_status_code}")
    if has_value(description_data.get("area_sqm")):
        lines.append(f"description_area_sqm: {description_data.get('area_sqm')}")

    if description_text:
        lines.extend(["", "【异步标的物描述】", description_text])

    analysis_text = "\n".join(lines).strip()
    return effective_seed, _redact_detail_analysis_text(analysis_text)

def fetch_browser_navigation_list_page(cdp_endpoint: str, target_url: str) -> tuple[str, str]:
    from tools import taobao_login_health

    try:
        existing_login_page = _reuse_existing_taobao_login_page(cdp_endpoint)
        if existing_login_page is not None:
            return existing_login_page
        existing_challenge_page = _reuse_existing_taobao_challenge_page(cdp_endpoint)
        if existing_challenge_page is not None:
            return existing_challenge_page
        taobao_login_health.compact_cdp_pages_if_needed(cdp_endpoint, reserve_for_new_page=True)
        opened = taobao_login_health.read_cdp_json(
            cdp_endpoint,
            "/json/new?" + quote(target_url, safe=""),
            method="PUT",
        )
    except Exception as error:
        _raise_cdp_endpoint_unavailable(cdp_endpoint, "open_list_page_target", error)
    target: dict[str, Any] | None = dict(opened) if isinstance(opened, dict) else None
    if target is None or not str(target.get("webSocketDebuggerUrl") or "").strip():
        try:
            matches = _find_matching_cdp_list_targets(cdp_endpoint, target_url)
        except Exception as error:
            _raise_cdp_endpoint_unavailable(cdp_endpoint, "find_list_page_target", error)
        target = matches[0] if matches else None
    if target is None:
        raise RuntimeError(f"unable to open CDP list page target: {target_url}")

    target_id = str(target.get("id") or "").strip()
    preserve_challenge_target = False
    try:
        try:
            html, final_url = _read_cdp_list_target_html(cdp_endpoint, target)
            preserve_challenge_target = is_challenge_page(html, final_url)
            return html, final_url
        except Exception as error:
            _raise_cdp_endpoint_unavailable(cdp_endpoint, "read_list_page_target_html", error)
    finally:
        # The node solver can only act on a challenge that remains attached to
        # CDP. Normal transient pages are still closed immediately.
        if target_id and not preserve_challenge_target:
            try:
                taobao_login_health.close_cdp_target(cdp_endpoint, target_id)
            except Exception:
                pass

def fetch_browser_list_page(cdp_endpoint: str, target_url: str) -> tuple[str, str] | None:
    try:
        browser_page = fetch_open_browser_list_page(
            cdp_endpoint,
            target_url,
            include_challenge=True,
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "event": "open_browser_list_page_probe_failed",
                    "target_url": target_url,
                    "error": safe_exception_text(error),
                },
                ensure_ascii=False,
            )
        )
        browser_page = None
    if browser_page is not None:
        return browser_page
    return fetch_browser_navigation_list_page(cdp_endpoint, target_url)

def recover_browser_list_page_after_challenge(
    cdp_endpoint: str,
    target_url: str,
    initial_page: tuple[str, str] | None,
    *,
    max_attempts: int | None = None,
    wait_seconds: float | None = None,
    solver_enabled: bool = True,
    api_base_url: str | None = None,
) -> tuple[str, str] | None:
    effective_max_attempts = max_attempts if max_attempts is not None else list_browser_recovery_max_attempts()
    effective_wait_seconds = wait_seconds if wait_seconds is not None else list_browser_recovery_wait_seconds()
    browser_page = initial_page
    attempts = 0
    while browser_page is not None and attempts < effective_max_attempts:
        html, final_url = browser_page
        if not is_challenge_page(html, final_url):
            return browser_page
        if attempts == 0 and solver_enabled:
            try:
                login_required = is_login_page(html, final_url)
                request_captcha_solver(
                    cdp_endpoint,
                    target_url,
                    api_base_url=api_base_url,
                    manual_only=login_required,
                )
            except Exception:
                pass
        attempts += 1
        if attempts >= effective_max_attempts:
            return browser_page
        time.sleep(effective_wait_seconds)
        browser_page = fetch_browser_list_page(cdp_endpoint, target_url)
    return browser_page

def fetch_list_page(
    http: requests.Session,
    *,
    cdp_endpoint: str,
    target_url: str,
    user_agent: str,
    referer_url: str | None = None,
    solver_enabled: bool | None = None,
    api_base_url: str | None = None,
) -> tuple[str, str, int | None, str]:
    browser_fallback_enabled = list_browser_fallback_enabled()
    solver_requested = (
        captcha_solver_enabled(default=browser_fallback_enabled)
        if solver_enabled is None
        else bool(solver_enabled)
    )
    effective_referer_url = str(referer_url or "").strip() or _default_list_referer_url(target_url)
    try:
        response = http.get(
            target_url,
            headers=build_navigation_headers(
                target_url=target_url,
                user_agent=user_agent,
                referer_url=effective_referer_url,
            ),
            timeout=list_http_timeout_seconds(),
            allow_redirects=True,
        )
        response.raise_for_status()
        if is_challenge_page(response.text, response.url):
            if not browser_fallback_enabled:
                if solver_requested:
                    try:
                        login_required = is_login_page(response.text, response.url)
                        request_captcha_solver(
                            cdp_endpoint,
                            target_url,
                            api_base_url=api_base_url,
                            manual_only=login_required,
                        )
                    except Exception:
                        pass
                return response.text, response.url, response.status_code, "http_cookie_challenge"
            browser_page = recover_browser_list_page_after_challenge(
                cdp_endpoint,
                target_url,
                fetch_browser_list_page(cdp_endpoint, target_url),
                solver_enabled=solver_requested,
                api_base_url=api_base_url,
            )
            if browser_page is not None:
                html, final_url = browser_page
                return html, final_url, None, "browser_page_after_http_challenge"
        return response.text, response.url, response.status_code, "http_cookie"
    except requests.RequestException:
        if not browser_fallback_enabled:
            raise
        browser_page = recover_browser_list_page_after_challenge(
            cdp_endpoint,
            target_url,
            fetch_browser_list_page(cdp_endpoint, target_url),
            solver_enabled=solver_requested,
            api_base_url=api_base_url,
        )
        if browser_page is None:
            raise
        html, final_url = browser_page
        return html, final_url, None, "browser_page"

def fetch_detail_with_browser(seed: dict[str, Any], *, cdp_endpoint: str) -> tuple[str, str, int, str]:
    from playwright.sync_api import sync_playwright
    from src.collection.adapters.taobao_auth_target import canonical_auth_target

    detail_url = seed.get("url")
    if not detail_url:
        raise RuntimeError("seed missing detail url")
    with sync_playwright() as p:
        browser = connect_browser_over_cdp(p, cdp_endpoint)
        try:
            if not browser.contexts:
                raise RuntimeError("attached browser has no contexts")
            context = browser.contexts[0]
            existing_target_challenge = False
            # Preserve login tabs. Old challenges, including other stages, are
            # not proof that this target is blocked with the current cookies.
            for existing_page in getattr(context, "pages", []):
                existing_url = str(getattr(existing_page, "url", "") or "")
                try:
                    existing_hostname = str(urlparse(existing_url).hostname or "").lower()
                except ValueError:
                    existing_hostname = ""
                is_taobao_page = existing_hostname == "taobao.com" or existing_hostname.endswith(
                    ".taobao.com"
                )
                if not (
                    is_taobao_page
                    or _is_taobao_login_target_url(existing_url)
                    or is_challenge_page("", existing_url)
                ):
                    continue
                try:
                    existing_html = str(existing_page.content() or "")
                except Exception:
                    existing_html = ""
                if _is_taobao_login_target_url(existing_url) or is_login_page(existing_html, existing_url):
                    raise DetailChallengeError("existing browser detail page", existing_url)
                if is_challenge_page(existing_html, existing_url):
                    try:
                        existing_target_challenge |= (
                            canonical_auth_target("detail", existing_url)
                            == canonical_auth_target("detail", str(detail_url))
                        )
                    except (ValueError, TypeError):
                        pass
            page = context.new_page()
            preserve_challenge_page = False
            try:
                configure_browser_identity_before_navigation(
                    context,
                    page,
                    cdp_endpoint=cdp_endpoint,
                )
                response = page.goto(detail_url, wait_until="domcontentloaded", timeout=90000)
                html = _wait_for_detail_ready(page)
                final_url = page.url
                if response and response.status >= 400:
                    raise RuntimeError(f"browser detail request returned HTTP {response.status}")
                if is_challenge_page(html, final_url):
                    preserve_challenge_page = not existing_target_challenge
                    raise DetailChallengeError("browser detail request", final_url)
                return html, final_url, len(html.encode("utf-8")), "browser_navigation"
            finally:
                if not preserve_challenge_page:
                    page.close()
        finally:
            detach_attached_cdp_browser(browser)

def fetch_detail_html(
    http: requests.Session,
    seed: dict[str, Any],
    browser_pages: dict[str, tuple[str, str]],
    *,
    cdp_endpoint: str,
    referer_url: str,
    user_agent: str | None = None,
) -> tuple[str, str, int, str]:
    browserless_seed_probe = _browserless_seed_probe()
    seed_id = str(seed.get("id"))
    if seed_id in browser_pages:
        html, final_url = browser_pages[seed_id]
        if not is_challenge_page(html, final_url):
            return html, final_url, len(html.encode("utf-8")), "open_browser_page"
        # A cached challenge predates any subsequent cookie import. Revalidate
        # with a fresh request before reporting another challenge to NAS.

    detail_url = seed.get("url")
    response = http.get(
        detail_url,
        headers=build_navigation_headers(
            target_url=str(detail_url),
            user_agent=str(user_agent or getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT)),
            referer_url=referer_url,
        ),
        timeout=60,
        allow_redirects=True,
    )
    response.raise_for_status()
    html = response.text
    if is_challenge_page(html, response.url):
        if not detail_browser_fallback_enabled():
            raise DetailChallengeError("HTTP detail request", response.url)
        return fetch_detail_with_browser(seed, cdp_endpoint=cdp_endpoint)
    return html, response.url, len(response.content), "http_cookie"

__all__ = (
    '_reuse_existing_taobao_login_page',
    '_reuse_existing_taobao_challenge_page',
    '_is_taobao_challenge_target_url',
    'fetch_open_browser_list_page',
    '_read_text_if_exists',
    '_redact_detail_analysis_text',
    '_detail_input_value',
    '_detail_node_text',
    '_detail_countdown_text',
    '_build_detail_analysis_input',
    'fetch_browser_navigation_list_page',
    'fetch_browser_list_page',
    'recover_browser_list_page_after_challenge',
    'fetch_list_page',
    'fetch_detail_with_browser',
    'fetch_detail_html',
)
