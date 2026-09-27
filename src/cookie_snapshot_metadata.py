"""Value-safe cookie metadata and stable snapshot comparison."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import TypedDict, cast


class CookieSummary(TypedDict):
    count: int
    domains: list[str]
    names: list[str]
    secure_count: int
    http_only_count: int
    session_count: int
    persistent_count: int
    earliest_expiry: str | None
    latest_expiry: str | None
    shape_fingerprint: str
    value_fingerprint: str


def _format_local_datetime(timestamp: float) -> str:
    # Retain the tool's numeric timestamp formatting after expiry normalization.
    if abs(timestamp) >= 10**11:
        timestamp /= 1000.0
    # Existing reports use the host's local wall time.
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")  # noqa: DTZ006


def _normalize_cookie_expiry(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(cast("str | float", value))
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    if abs(numeric) >= 10**11:
        numeric /= 1000.0
    return numeric


def _cookie_shape_fingerprint(cookies: Iterable[Mapping[str, object]]) -> str:
    normalized = [
        {
            "name": str(cookie.get("name") or ""),
            "domain": str(cookie.get("domain") or ""),
            "path": str(cookie.get("path") or "/"),
            "secure": bool(cookie.get("secure")),
            "httpOnly": bool(cookie.get("httpOnly")),
            "session": _normalize_cookie_expiry(cookie.get("expires")) is None,
        }
        for cookie in cookies
    ]
    payload = json.dumps(
        sorted(
            normalized,
            key=lambda item: (
                str(item["domain"]),
                str(item["name"]),
                str(item["path"]),
            ),
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cookie_value_fingerprint(cookies: Iterable[Mapping[str, object]]) -> str:
    normalized = [
        {
            "name": str(cookie.get("name") or ""),
            "domain": str(cookie.get("domain") or ""),
            "path": str(cookie.get("path") or "/"),
            "value": str(cookie.get("value") or ""),
        }
        for cookie in cookies
    ]
    payload = json.dumps(
        sorted(
            normalized,
            key=lambda item: (
                str(item["domain"]),
                str(item["name"]),
                str(item["path"]),
            ),
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cookie_key(cookie: Mapping[str, object]) -> str:
    return f"{cookie.get('name') or ''!s}|{cookie.get('domain') or ''!s}|{cookie.get('path') or '/'!s}"


def summarize_cookie_snapshot(cookies: Iterable[Mapping[str, object]]) -> CookieSummary:
    cookie_list = list(cookies)
    persistent_expiries = [
        normalized_expiry
        for normalized_expiry in (
            _normalize_cookie_expiry(cookie.get("expires")) for cookie in cookie_list
        )
        if normalized_expiry is not None
    ]
    return {
        "count": len(cookie_list),
        "domains": sorted(
            {
                str(cookie.get("domain") or "")
                for cookie in cookie_list
                if str(cookie.get("domain") or "")
            }
        ),
        "names": sorted(
            {
                str(cookie.get("name") or "")
                for cookie in cookie_list
                if str(cookie.get("name") or "")
            }
        ),
        "secure_count": sum(1 for cookie in cookie_list if bool(cookie.get("secure"))),
        "http_only_count": sum(
            1 for cookie in cookie_list if bool(cookie.get("httpOnly"))
        ),
        "session_count": len(cookie_list) - len(persistent_expiries),
        "persistent_count": len(persistent_expiries),
        "earliest_expiry": _format_local_datetime(min(persistent_expiries))
        if persistent_expiries
        else None,
        "latest_expiry": _format_local_datetime(max(persistent_expiries))
        if persistent_expiries
        else None,
        "shape_fingerprint": _cookie_shape_fingerprint(cookie_list),
        "value_fingerprint": _cookie_value_fingerprint(cookie_list),
    }


def diff_cookie_snapshots(
    left_cookies: Iterable[Mapping[str, object]],
    right_cookies: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    left_list = list(left_cookies)
    right_list = list(right_cookies)
    left_summary = summarize_cookie_snapshot(left_list)
    right_summary = summarize_cookie_snapshot(right_list)

    left_domains = set(left_summary["domains"])
    right_domains = set(right_summary["domains"])
    left_names = set(left_summary["names"])
    right_names = set(right_summary["names"])
    left_keys = {_cookie_key(cookie) for cookie in left_list}
    right_keys = {_cookie_key(cookie) for cookie in right_list}

    return {
        "added_domains": sorted(right_domains - left_domains),
        "removed_domains": sorted(left_domains - right_domains),
        "added_names": sorted(right_names - left_names),
        "removed_names": sorted(left_names - right_names),
        "added_keys": sorted(right_keys - left_keys),
        "removed_keys": sorted(left_keys - right_keys),
        "shared_key_count": len(left_keys & right_keys),
        "shape_fingerprint_equal": left_summary["shape_fingerprint"]
        == right_summary["shape_fingerprint"],
        "value_fingerprint_equal": left_summary["value_fingerprint"]
        == right_summary["value_fingerprint"],
    }
