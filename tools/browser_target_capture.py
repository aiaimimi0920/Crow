"""One attached-browser capture lifecycle for list and detail collection."""

from tools.browser_cdp_session import held_cdp_session
from tools.browser_owned_page import owned_background_page
from tools.capture_browser_codes import navigation_error_code
from tools.capture_budget import (
    CaptureBudgetExceeded,
    bounded_capture_timeout,
    check_capture_budget,
)
from tools.capture_progress import capture_driver, mark_capture_stage


class BrowserTargetChallenge(RuntimeError):
    """Private in-process evidence; only adapters serialize challenge identity."""

    def __init__(self, operation, challenge_url, html=""):
        super().__init__(operation)
        self.operation = operation
        self.challenge_url = challenge_url
        self.html = html


def _read_existing(page):
    mark_capture_stage("existing_page_read")
    return str(
        page.locator("html").inner_html(timeout=bounded_capture_timeout(5000)) or ""
    )


def _navigation_challenge(page, error, matches, is_challenge, is_login, ready_stage):
    """Only recover positive, bound challenge evidence from transient navigation."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    check_capture_budget()
    if not isinstance(error, PlaywrightTimeoutError) and navigation_error_code(
        error
    ) not in {"ERR_TIMED_OUT", "ERR_CONNECTION_CLOSED", "ERR_CONNECTION_TIMED_OUT"}:
        return None
    result = None
    try:
        if not matches(str(page.url or "")):
            return None
        mark_capture_stage(ready_stage)
        html = str(
            page.locator("html").inner_html(timeout=bounded_capture_timeout(2000)) or ""
        )
        check_capture_budget()
        final_url = str(page.url or "")
        if (
            matches(final_url)
            and is_challenge(html, final_url)
            and not is_login(html, final_url)
        ):
            result = html, final_url
    except CaptureBudgetExceeded:
        raise
    except Exception:  # noqa: BLE001 -- optional evidence must not mask navigation failure
        result = None
    check_capture_budget()
    return result


def _has_live_duplicate(context, candidates, matches, is_challenge, is_login):
    for candidate in candidates:
        check_capture_budget()
        duplicate = False
        try:
            if not any(candidate is p for p in context.pages) or not matches(
                str(candidate.url or "")
            ):
                continue
            html = _read_existing(candidate)
            current_url = str(candidate.url or "")
            duplicate = (
                any(candidate is p for p in context.pages)
                and matches(current_url)
                and is_challenge(html, current_url)
                and not is_login(html, current_url)
            )
        except Exception:  # noqa: BLE001 -- uncertainty cannot authorize discarding a challenge
            duplicate = False
        check_capture_budget()
        if duplicate:
            return True
    return False


def capture_attached_target(
    target_url,
    *,
    cdp_endpoint,
    matches,
    connect_browser,
    detach_browser,
    is_login_target,
    is_challenge,
    is_login,
    configure_page,
    wait_for_ready,
    payload_authenticated,
    label,
):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    ready_stage = f"{label}_ready"
    with capture_driver(sync_playwright) as driver:
        mark_capture_stage("cdp_connect")
        browser = connect_browser(driver, cdp_endpoint)
        try:
            if not browser.contexts:
                raise RuntimeError("attached browser has no contexts")
            context = browser.contexts[0]
            candidates = []
            mark_capture_stage("existing_pages")
            # URL metadata filters first: never scan another task's document.
            for existing in list(getattr(context, "pages", [])):
                check_capture_budget()
                url = str(getattr(existing, "url", "") or "")
                if is_login_target(url):
                    raise BrowserTargetChallenge(f"existing browser {label} page", url)
                if not matches(url):
                    continue
                try:
                    html = _read_existing(existing)
                except Exception:  # noqa: BLE001 -- stale borrowed tabs cannot block a fresh request
                    html = ""
                check_capture_budget()
                current_url = str(getattr(existing, "url", "") or "")
                if is_login_target(current_url) or is_login(html, current_url):
                    raise BrowserTargetChallenge(
                        f"existing browser {label} page", current_url, html
                    )
                if matches(current_url) and is_challenge(html, current_url):
                    candidates.append(existing)

            # Old challenge DOM is not fresh business-access proof in either stage.
            mark_capture_stage("page_create")
            check_capture_budget()
            with owned_background_page(context, cdp_endpoint) as owned:
                page = owned.page
                mark_capture_stage("page_session")
                check_capture_budget()
                with held_cdp_session(context, page) as session:
                    mark_capture_stage("page_configure")
                    configure_page(
                        context, page, cdp_endpoint=cdp_endpoint, cdp_session=session
                    )
                    mark_capture_stage("page_navigate")
                    navigation_challenge = None
                    try:
                        response = page.goto(
                            target_url,
                            wait_until="domcontentloaded",
                            timeout=bounded_capture_timeout(90000),
                        )
                    except PlaywrightError as error:
                        navigation_challenge = _navigation_challenge(
                            page, error, matches, is_challenge, is_login, ready_stage
                        )
                        if navigation_challenge is None:
                            raise
                        owned.preserve = True
                        response = None
                    if navigation_challenge is None:
                        mark_capture_stage(ready_stage)
                        check_capture_budget()
                        html = wait_for_ready(page)
                        check_capture_budget()
                        final_url = str(page.url or "")
                    else:
                        html, final_url = navigation_challenge
                check_capture_budget()
                if navigation_challenge is not None or is_challenge(html, final_url):
                    owned.preserve = True
                    if candidates:
                        owned.preserve = not _has_live_duplicate(
                            context, candidates, matches, is_challenge, is_login
                        )
                    raise BrowserTargetChallenge(
                        f"browser {label} request", final_url, html
                    )
                if response and response.status >= 400:
                    raise RuntimeError(
                        f"browser {label} request returned HTTP {response.status}"
                    )
                if not matches(final_url) or not payload_authenticated(html, final_url):
                    raise RuntimeError(f"browser {label} payload was not confirmed")
                return html, final_url, len(html.encode("utf-8")), "browser_navigation"
        finally:
            mark_capture_stage("browser_detach")
            detach_browser(browser)
