"""Taobao list-page parsing and cookie-backed health probes."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from html import unescape
from typing import Protocol, cast
from urllib.parse import urlparse

import requests

from src.cdp_cookie_transport import DEFAULT_USER_AGENT
from src.collection.adapters.taobao_health import redact_taobao_sensitive_text

DEFAULT_ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9,en;q=0.8"
DEFAULT_NAVIGATION_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8"
)
_SCRIPT_RE = re.compile(
    r"<script[^>]+id=['\"]sf-item-list-data['\"][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


class PageResponse(Protocol):
    @property
    def text(self) -> str: ...
    @property
    def url(self) -> str: ...
    @property
    def status_code(self) -> int: ...


class PageSession(Protocol):
    def get(
        self, url: str, *, headers: dict[str, str], timeout: int, allow_redirects: bool
    ) -> PageResponse: ...


def _site_boundary(target_url: str, referer_url: str) -> str:
    target_host = str(urlparse(target_url).hostname or "").lower()
    referer_host = str(urlparse(referer_url).hostname or "").lower()
    if not referer_host:
        return "none"
    if target_host == referer_host:
        return "same-origin"
    target_parts = target_host.split(".")
    referer_parts = referer_host.split(".")
    if (
        len(target_parts) >= 2
        and len(referer_parts) >= 2
        and ".".join(target_parts[-2:]) == ".".join(referer_parts[-2:])
    ):
        return "same-site"
    return "cross-site"


def build_navigation_headers(
    *,
    target_url: str,
    user_agent: str,
    referer_url: str,
    accept_language: str = DEFAULT_ACCEPT_LANGUAGE,
) -> dict[str, str]:
    headers = {
        "User-Agent": str(user_agent or DEFAULT_USER_AGENT),
        "Accept": DEFAULT_NAVIGATION_ACCEPT,
        "Accept-Language": str(accept_language or DEFAULT_ACCEPT_LANGUAGE),
        "Cache-Control": "max-age=0",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": _site_boundary(target_url, referer_url),
        "Sec-Fetch-User": "?1",
    }
    if str(referer_url or "").strip():
        headers["Referer"] = str(referer_url)
    return headers


def build_session_from_playwright_cookies(
    cookies: Iterable[Mapping[str, object]],
) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    for cookie in cookies:
        session.cookies.set(
            str(cookie["name"]),
            str(cookie["value"]),
            domain=cast("str | None", cookie.get("domain")),
            path=cast("str", cookie.get("path", "/")),
        )
    return session


def extract_list_payload(html: str) -> object:
    match = _SCRIPT_RE.search(html)
    if not match:
        return None
    return json.loads(unescape(match.group(1).strip()))


def _looks_like_login_page(text: str, final_url: str) -> bool:
    if "login.taobao.com" in final_url:
        return True
    strong_markers = ("扫码登录", "账户登录", "密码登录", "短信登录", "忘记密码")
    return any(marker in text for marker in strong_markers)


def summarize_list_page(html: str, *, final_url: str) -> dict[str, object]:
    text = html or ""
    lowered_final_url = str(final_url or "").lower()
    payload = extract_list_payload(text)
    data = payload.get("data") if isinstance(payload, dict) else None
    items = cast("list[Mapping[str, object]]", data) if isinstance(data, list) else []
    body_has_punish = (
        "_____tmd_____/punish" in text
        or "x5secdata=" in text
        or "_____tmd_____/punish" in lowered_final_url
        or "x5secdata=" in lowered_final_url
    )
    strong_captcha_markers = (
        "RGV587_ERROR",
        "请完成验证",
        "安全验证",
        "霸下通用 web 页面-验证码",
        "滑动验证",
        "人机验证",
        "异常流量",
        "访问受限",
    )
    body_has_captcha = any(marker in text for marker in strong_captcha_markers) or (
        payload is None and "验证码" in text
    )
    body_snippet = redact_taobao_sensitive_text(text[:260].replace("\n", " ")[:260])
    return {
        "has_script": payload is not None,
        "item_count": len(items) if payload is not None else None,
        "first_ids": [item.get("id") for item in items[:5]],
        "first_urls": [item.get("itemUrl") or item.get("url") for item in items[:5]],
        "body_has_login": _looks_like_login_page(text, final_url),
        "body_has_captcha": body_has_captcha,
        "body_has_punish": body_has_punish,
        "body_has_challenge": body_has_captcha or body_has_punish,
        "body_snippet": body_snippet,
    }


def probe_seed_page(
    url: str,
    *,
    cookies: Iterable[Mapping[str, object]],
    session: PageSession | None = None,
    timeout: int = 30,
    user_agent: str | None = None,
    referer_url: str = "https://sf.taobao.com/",
) -> dict[str, object]:
    http = session or build_session_from_playwright_cookies(cookies)
    response = http.get(
        url,
        headers=build_navigation_headers(
            target_url=url,
            user_agent=str(user_agent or DEFAULT_USER_AGENT),
            referer_url=referer_url,
        ),
        timeout=timeout,
        allow_redirects=True,
    )
    summary = summarize_list_page(response.text, final_url=response.url)
    summary.update(
        {
            "status": response.status_code,
            "final_url": response.url,
        }
    )
    return summary
