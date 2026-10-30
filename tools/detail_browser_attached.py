"""Capture a detail page while retaining the attached browser's ownership."""

import logging
from typing import Any
from urllib.parse import urlparse

from src.collection.adapters.taobao_auth_target import canonical_auth_target
from tools.browser_cdp_session import held_cdp_session
from tools.capture_browser_codes import navigation_error_code
from tools.capture_budget import (
    CaptureBudgetExceeded,
    bounded_capture_timeout,
    check_capture_budget,
)
from tools.capture_progress import capture_driver, mark_capture_stage

logger = logging.getLogger(__name__)


def _navigation_challenge(page, target_url, error, is_challenge, is_login):
    """Recover only a positively bound challenge, never a partial success."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    check_capture_budget()
    if not isinstance(error, PlaywrightTimeoutError) and navigation_error_code(
        error
    ) not in {
        "ERR_TIMED_OUT",
        "ERR_CONNECTION_CLOSED",
        "ERR_CONNECTION_TIMED_OUT",
    }:
        return None
    result = None
    try:
        target = canonical_auth_target("detail", str(target_url))
        if canonical_auth_target("detail", str(page.url or "")) != target:
            return None
        mark_capture_stage("detail_ready")
        html = str(
            page.locator("html").inner_html(timeout=bounded_capture_timeout(2000)) or ""
        )
        check_capture_budget()
        final_url = str(page.url or "")
        if (
            canonical_auth_target("detail", final_url) == target
            and is_challenge(html, final_url)
            and not is_login(html, final_url)
        ):
            result = (html, final_url)
    except CaptureBudgetExceeded:
        raise
    except Exception:  # noqa: BLE001 -- optional evidence must not replace the navigation error
        result = None
    check_capture_budget()
    return result


def _has_live_duplicate(context, candidates, target_url, is_challenge, is_login):
    """A pre-navigation challenge is not proof that a duplicate still exists."""
    for candidate in candidates:
        check_capture_budget()
        duplicate = False
        try:
            target = canonical_auth_target("detail", str(target_url))
            if not any(candidate is page for page in context.pages):
                continue
            before_url = str(candidate.url or "")
            if canonical_auth_target("detail", before_url) != target:
                continue
            mark_capture_stage("existing_page_read")
            html = str(
                candidate.locator("html").inner_html(
                    timeout=bounded_capture_timeout(5000)
                )
                or ""
            )
            current_url = str(candidate.url or "")
            duplicate = (
                any(candidate is page for page in context.pages)
                and canonical_auth_target("detail", current_url) == target
                and is_challenge(html, current_url)
                and not is_login(html, current_url)
            )
        except Exception:  # noqa: BLE001 -- unknown state never authorizes closing the new page
            duplicate = False
        check_capture_budget()
        if duplicate:
            return True
    return False


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
    from playwright.sync_api import Error as PlaywrightError
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
            existing_target_challenges = []
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
                        if canonical_auth_target(
                            "detail", existing_url
                        ) == canonical_auth_target("detail", str(detail_url)):
                            existing_target_challenges.append(existing_page)
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
                    navigation_challenge = None
                    try:
                        response = page.goto(
                            detail_url,
                            wait_until="domcontentloaded",
                            timeout=bounded_capture_timeout(90000),
                        )
                    except PlaywrightError as error:
                        navigation_challenge = _navigation_challenge(
                            page, detail_url, error, is_challenge, is_login
                        )
                        if navigation_challenge is None:
                            raise
                        # Retain already verified evidence even if session cleanup
                        # consumes the remaining budget or is cancelled.
                        preserve_challenge_page = True
                        response = None
                    if navigation_challenge is None:
                        mark_capture_stage("detail_ready")
                        check_capture_budget()
                        html = wait_for_detail(page)
                        check_capture_budget()
                        final_url = page.url
                    else:
                        html, final_url = navigation_challenge
                check_capture_budget()
                # A verified challenge can itself return an HTTP error. Preserve
                # its page and typed outcome before applying generic status policy.
                if navigation_challenge is not None or is_challenge(html, final_url):
                    # Preserve first, including if the bounded recheck itself fails.
                    preserve_challenge_page = True
                    if existing_target_challenges:
                        preserve_challenge_page = not _has_live_duplicate(
                            context,
                            existing_target_challenges,
                            detail_url,
                            is_challenge,
                            is_login,
                        )
                    raise challenge_error("browser detail request", final_url)
                if response and response.status >= 400:
                    raise RuntimeError(
                        f"browser detail request returned HTTP {response.status}"
                    )
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
