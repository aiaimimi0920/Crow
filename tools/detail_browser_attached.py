"""Capture a detail page while retaining the attached browser's ownership."""

import logging
from typing import Any
from urllib.parse import urlparse

from src.collection.adapters.taobao_auth_target import canonical_auth_target
from tools.browser_cdp_session import held_cdp_session
from tools.capture_budget import bounded_capture_timeout, check_capture_budget
from tools.capture_progress import capture_driver, mark_capture_stage

logger = logging.getLogger(__name__)


def capture_attached_detail(
    seed: dict[str, Any],
    *,
    cdp_endpoint: str,
    connect_browser,
    detach_browser,
    is_login_target,
    is_challenge,
    is_login,
    challenge_error,
    configure_page,
    wait_for_detail,
) -> tuple[str, str, int, str]:
    from playwright.sync_api import sync_playwright

    detail_url = seed.get("url")
    if not detail_url:
        raise RuntimeError("seed missing detail url")
    with capture_driver(sync_playwright) as p:
        mark_capture_stage("cdp_connect")
        browser = connect_browser(p, cdp_endpoint)
        try:
            if not browser.contexts:
                raise RuntimeError("attached browser has no contexts")
            context = browser.contexts[0]
            existing_target_challenge = False
            mark_capture_stage("existing_pages")
            # Read existing tabs without focusing, closing, or navigating them.
            for existing_page in getattr(context, "pages", []):
                check_capture_budget()
                existing_url = str(getattr(existing_page, "url", "") or "")
                try:
                    existing_hostname = str(
                        urlparse(existing_url).hostname or ""
                    ).lower()
                except ValueError:
                    existing_hostname = ""
                is_taobao_page = (
                    existing_hostname == "taobao.com"
                    or existing_hostname.endswith(".taobao.com")
                )
                if not (
                    is_taobao_page
                    or is_login_target(existing_url)
                    or is_challenge("", existing_url)
                ):
                    continue
                try:
                    mark_capture_stage("existing_page_read")
                    # content() has no timeout; classification only needs the
                    # document children (title, scripts, forms and body).
                    existing_html = str(
                        existing_page.locator("html").inner_html(
                            timeout=bounded_capture_timeout(5000)
                        )
                        or ""
                    )
                except Exception:  # noqa: BLE001 -- a stale tab must not prevent URL-only classification
                    existing_html = ""
                check_capture_budget()
                if is_login_target(existing_url) or is_login(
                    existing_html, existing_url
                ):
                    raise challenge_error("existing browser detail page", existing_url)
                if is_challenge(existing_html, existing_url):
                    try:
                        existing_target_challenge |= canonical_auth_target(
                            "detail", existing_url
                        ) == canonical_auth_target("detail", str(detail_url))
                    except (ValueError, TypeError):
                        pass
            mark_capture_stage("page_create")
            check_capture_budget()
            page = context.new_page()
            preserve_challenge_page = False
            operation_failed = True
            try:
                mark_capture_stage("page_session")
                check_capture_budget()
                with held_cdp_session(context, page) as session:
                    mark_capture_stage("page_configure")
                    configure_page(
                        context,
                        page,
                        cdp_endpoint=cdp_endpoint,
                        cdp_session=session,
                    )
                    mark_capture_stage("page_navigate")
                    response = page.goto(
                        detail_url,
                        wait_until="domcontentloaded",
                        timeout=bounded_capture_timeout(90000),
                    )
                    mark_capture_stage("detail_ready")
                    check_capture_budget()
                    html = wait_for_detail(page)
                    check_capture_budget()
                final_url = page.url
                if response and response.status >= 400:
                    raise RuntimeError(
                        f"browser detail request returned HTTP {response.status}"
                    )
                if is_challenge(html, final_url):
                    preserve_challenge_page = not existing_target_challenge
                    raise challenge_error("browser detail request", final_url)
                result = (
                    html,
                    final_url,
                    len(html.encode("utf-8")),
                    "browser_navigation",
                )
                operation_failed = False
                return result
            finally:
                if not preserve_challenge_page:
                    mark_capture_stage("page_close")
                    try:
                        page.close()
                    except Exception as error:
                        # Preserve the primary failure or cancellation, not raw text.
                        if not operation_failed:
                            raise
                        logger.warning(
                            "Owned capture page cleanup failed (%s)",
                            type(error).__name__,
                        )
        finally:
            mark_capture_stage("browser_detach")
            detach_browser(browser)
