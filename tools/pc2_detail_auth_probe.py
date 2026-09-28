"""Verify a fresh detail request in PC2's imported browser session."""

from src.collection.adapters.taobao_auth_target import auth_target, same_auth_target
from tools.live_smoke_auth import _detail_page_has_ready_marker, is_challenge_page


def detail_payload_authenticated(html: str, final_url: str, target_url: str) -> bool:
    return (
        same_auth_target("detail", final_url, target_url)
        and not is_challenge_page(html, final_url)
        and _detail_page_has_ready_marker(html)
    )


def probe_detail_access(cdp_endpoint: str, target_url: str) -> bool:
    from playwright.sync_api import sync_playwright

    target_url = auth_target("detail", target_url)
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_endpoint, timeout=15000)
        page = None
        try:
            if not browser.contexts:
                return False
            page = browser.contexts[0].new_page()
            response = page.goto(
                target_url, wait_until="domcontentloaded", timeout=45000
            )
            if response is None or response.status >= 400:
                return False
            # Hydrated detail fields may appear after DOMContentLoaded.
            for attempt in range(21):
                html = page.content()
                if is_challenge_page(html, page.url):
                    return False
                if detail_payload_authenticated(html, page.url, target_url):
                    return True
                if attempt < 20:
                    page.wait_for_timeout(500)
            return False
        finally:
            if page is not None:
                page.close()
            # Only the probe-owned page is closed; keep the external browser alive.
