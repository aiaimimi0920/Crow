"""Taobao health classification and credential-safe diagnostic output."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .taobao_solver_target import _is_taobao_login_target, _split_web_target_url

HEALTHY_LIST_PAYLOAD = "healthy_list_payload"

PARTIAL_AVAILABLE = "partial_available"

ALL_SAMPLES_BLOCKED = "all_samples_blocked"

LOGIN_REQUIRED = "login_required"

CHALLENGE_REQUIRED = "challenge_required"

PUNISH_PAGE = "punish_page"

CAPTCHA_PAGE = "captcha_page"

CDP_UNREACHABLE = "cdp_unreachable"

UNKNOWN_BLOCKED = "unknown_blocked"

SENSITIVE_QUERY_KEYS = {
    "x5secdata",
    "x5sec",
    "cookie2",
    "sgcookie",
    "_tb_token_",
}

SENSITIVE_INLINE_PATTERNS = (
    re.compile(r"x5secdata\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"cookie2\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"sgcookie\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"_tb_token_\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
)


def redact_taobao_sensitive_text(value: str) -> str:
    redacted = value
    for pattern in SENSITIVE_INLINE_PATTERNS:
        redacted = pattern.sub("taobao_security_value=<redacted>", redacted)
    return redacted


def redact_taobao_sensitive_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return redact_taobao_sensitive_text(url)
    query = urlencode(
        [
            (key, redact_taobao_sensitive_text(value))
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in SENSITIVE_QUERY_KEYS
        ],
        doseq=True,
    )
    return redact_taobao_sensitive_text(
        urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))
    )


def redact_taobao_health_output(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): redact_taobao_health_output(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_taobao_health_output(item) for item in value]
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return redact_taobao_sensitive_url(value)
        return redact_taobao_sensitive_text(value)
    return value


def _summary_flag(summary: Mapping[str, object], key: str) -> bool:
    return summary.get(key) is True


def classify_taobao_health(
    html: str,
    *,
    final_url: str,
    list_summary: Mapping[str, object] | None = None,
    payload_present: bool,
) -> dict[str, object]:
    summary = list_summary or {}
    text = html or ""
    lowered_text = text.lower()
    lowered_url = (final_url or "").lower()

    has_login = _summary_flag(summary, "body_has_login") or _is_taobao_login_target(
        _split_web_target_url(final_url)
    )
    has_punish = (
        _summary_flag(summary, "body_has_punish")
        or "_____tmd_____" in lowered_url
        or "_____tmd_____" in lowered_text
        or "/punish" in lowered_url
        or "/punish" in lowered_text
        or "x5secdata=" in lowered_text
    )
    has_captcha = _summary_flag(summary, "body_has_captcha") or (
        not payload_present
        and (
            "captcha" in lowered_text
            or "验证码" in text
            or "霸下通用 web 页面-验证码" in text
        )
    )
    has_challenge = (
        _summary_flag(summary, "body_has_challenge")
        or "challenge" in lowered_url
        or (
            not payload_present
            and (
                "challenge" in lowered_text
                or "anti-bot" in lowered_text
                or "霸下" in text
            )
        )
    )

    if payload_present and not (
        has_login or has_punish or has_captcha or has_challenge
    ):
        return {
            "status": HEALTHY_LIST_PAYLOAD,
            "healthy": True,
            "action": "none",
            "final_url": final_url,
        }
    if has_punish:
        return {
            "status": PUNISH_PAGE,
            "healthy": False,
            "action": "complete_taobao_security_verification",
            "final_url": final_url,
        }
    if has_captcha:
        return {
            "status": CAPTCHA_PAGE,
            "healthy": False,
            "action": "complete_taobao_security_verification",
            "final_url": final_url,
        }
    if has_challenge:
        return {
            "status": CHALLENGE_REQUIRED,
            "healthy": False,
            "action": "complete_taobao_security_verification",
            "final_url": final_url,
        }
    if has_login:
        return {
            "status": LOGIN_REQUIRED,
            "healthy": False,
            "action": "complete_taobao_login",
            "final_url": final_url,
        }
    return {
        "status": UNKNOWN_BLOCKED,
        "healthy": False,
        "action": "inspect_taobao_session",
        "final_url": final_url,
    }
