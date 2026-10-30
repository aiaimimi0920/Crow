"""Cookie-backed proof of the exact detail item, without browser or tool imports."""

from collections.abc import Iterable, Mapping
from time import monotonic
from urllib.parse import parse_qsl, urljoin

from src.auth_cookie_probe_budget import current_detail_probe_budget

from .taobao_auth_target import auth_target, same_auth_target
from .taobao_health import classify_taobao_health, redact_taobao_sensitive_url
from .taobao_list_probe import (
    PageSession,
    build_navigation_headers,
    build_session_from_playwright_cookies,
    summarize_list_page,
)
from .taobao_solver_target import (
    _is_taobao_login_target,
    _is_taobao_target,
    _split_web_target_url,
)


def _redirect_kind(headers: object, target: str) -> str:
    """Project Location to an enum only; this never authorizes a redirect."""
    location = (
        next(
            (value for key, value in headers.items() if str(key).lower() == "location"),
            None,
        )
        if isinstance(headers, Mapping)
        else None
    )
    if location is None or location == "":
        return "missing_location"
    if (
        not isinstance(location, str)
        or len(location) > 8192
        or "\\" in location
        or any(ord(char) <= 32 or ord(char) == 127 for char in location)
    ):
        return "invalid_location"
    try:
        parsed = _split_web_target_url(urljoin(target, location))
        if parsed is None or parsed.port not in {None, 443}:
            return "invalid_location"
        if parsed.scheme != "https":
            return "non_https_target"
        if not _is_taobao_target(parsed):
            return "external_target"
        if _is_taobao_login_target(parsed):
            return "login_required"
        keys = {
            key.lower()
            for key, _ in parse_qsl(
                parsed.query, keep_blank_values=True, max_num_fields=128
            )
        }
        if any(
            marker in parsed.path.lower()
            for marker in ("_____tmd_____", "/punish", "captcha", "challenge")
        ) or keys.intersection({"x5secdata", "x5sec"}):
            return "challenge_required"
        destination = parsed.geturl()
        if same_auth_target("detail", destination, target):
            return "same_detail"
        try:
            auth_target("detail", destination)
        except ValueError:
            return "other_taobao"
        return "other_detail"
    except (ValueError, TypeError):
        return "invalid_location"


def _detail_transport_identity(value: str) -> tuple[str, str, int, str] | None:
    if "?" in value or "#" in value:
        return None
    parsed = _split_web_target_url(value)
    if parsed is None:
        return None
    try:
        auth_target("detail", value)
    except (TypeError, ValueError):
        return None
    return parsed.scheme, str(parsed.hostname), parsed.port or 443, parsed.path


def _same_detail_redirect(headers: object, target: str) -> str | None:
    """Identity equivalence alone never authorizes a server-provided URL."""
    if _redirect_kind(headers, target) != "same_detail":
        return None
    assert isinstance(headers, Mapping)
    location = next(
        value for key, value in headers.items() if str(key).lower() == "location"
    )
    if not isinstance(location, str) or "?" in location or "#" in location:
        return None
    parsed = _split_web_target_url(urljoin(target, location))
    if parsed is None or parsed.query or parsed.fragment:
        return None
    # auth_target enforces the two exact hosts/paths and same_auth_target the ID.
    if not same_auth_target("detail", parsed.geturl(), target):
        return None
    destination = parsed.geturl()
    identity = _detail_transport_identity(destination)
    return (
        destination
        if identity is not None and identity != _detail_transport_identity(target)
        else None
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
    allow_same_detail_redirect: bool = False,
) -> dict[str, object]:
    target = auth_target("detail", url)
    http = session or build_session_from_playwright_cookies(cookies)
    budget = current_detail_probe_budget()
    deadline = monotonic() + timeout
    if budget is not None:
        budget.consume()
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
    followed = False
    requested_target = target
    if (
        allow_same_detail_redirect
        and budget is not None
        and budget.available
        and response.status_code in {301, 302, 303, 307, 308}
    ):
        destination = _same_detail_redirect(getattr(response, "headers", None), target)
        remaining = int(deadline - monotonic())
        if destination is not None and remaining >= 1:
            budget.consume()
            response = http.get(
                destination,
                headers=build_navigation_headers(
                    target_url=destination, user_agent=user_agent, referer_url=target
                ),
                timeout=remaining,
                allow_redirects=False,
            )
            followed = True
            requested_target = destination
    healthy = 200 <= response.status_code < 300 and detail_payload_authenticated(
        response.text, response.url, target
    )
    if followed:
        healthy = bool(
            healthy
            and monotonic() < deadline
            and _detail_transport_identity(response.url)
            == _detail_transport_identity(requested_target)
        )
    result: dict[str, object] = {
        "scope": "detail",
        "check_url": target,
        "final_url": target if followed else redact_taobao_sensitive_url(response.url),
        "http_status": response.status_code,
        "healthy": healthy,
        "status": "healthy_detail_payload" if healthy else "detail_auth_unverified",
    }
    if followed:
        result["same_detail_redirect_followed"] = True
        result["http_request_count"] = 2
    if response.status_code in {301, 302, 303, 307, 308}:
        result["redirect_kind"] = _redirect_kind(
            getattr(response, "headers", None), requested_target
        )
    return result
