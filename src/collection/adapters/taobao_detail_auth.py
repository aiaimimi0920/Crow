"""Cookie-backed proof of the exact detail item, without browser or tool imports."""

from collections.abc import Iterable, Mapping

from .taobao_auth_target import auth_target, same_auth_target
from .taobao_health import classify_taobao_health, redact_taobao_sensitive_url
from .taobao_list_probe import (
    PageSession,
    build_navigation_headers,
    build_session_from_playwright_cookies,
    summarize_list_page,
)


def detail_page_has_ready_marker(html: str) -> bool:
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


def detail_payload_authenticated(html: str, final_url: str, target_url: str) -> bool:
    if not same_auth_target("detail", final_url, target_url):
        return False
    ready = detail_page_has_ready_marker(html)
    summary = summarize_list_page(html, final_url=final_url)
    classification = classify_taobao_health(
        html, final_url=final_url, list_summary=summary, payload_present=ready
    )
    return ready and classification.get("healthy") is True


def probe_detail_page(
    url: str,
    *,
    cookies: Iterable[Mapping[str, object]],
    session: PageSession | None = None,
    timeout: int = 15,
    user_agent: str = "",
) -> dict[str, object]:
    target = auth_target("detail", url)
    http = session or build_session_from_playwright_cookies(cookies)
    response = http.get(
        target,
        headers=build_navigation_headers(
            target_url=target,
            user_agent=user_agent,
            referer_url="https://sf.taobao.com/",
        ),
        timeout=timeout,
        # Proof is for this exact allowlisted URL. Never follow a server-provided
        # redirect into another origin or a private-network destination.
        allow_redirects=False,
    )
    healthy = 200 <= response.status_code < 300 and detail_payload_authenticated(
        response.text, response.url, target
    )
    return {
        "scope": "detail",
        "check_url": target,
        "final_url": redact_taobao_sensitive_url(response.url),
        "http_status": response.status_code,
        "healthy": healthy,
        "status": "healthy_detail_payload" if healthy else "detail_auth_unverified",
    }
