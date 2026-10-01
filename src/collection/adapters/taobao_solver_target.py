"""Preserve Taobao collection identity while removing stale solver challenge data."""

import re
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit


def _split_web_target_url(value: object) -> SplitResult | None:
    """Reject ambiguous browser authorities before using a URL as an identity."""
    target_url = str(value or "").strip(" ")
    if (
        not target_url
        or "\\" in target_url
        or any(ord(char) <= 32 or ord(char) == 127 for char in target_url)
    ):
        return None
    try:
        parsed = urlsplit(target_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "%" in parsed.netloc
        ):
            return None
        # Accessing port validates malformed and out-of-range port values.
        _ = parsed.port
    except ValueError:
        return None
    return parsed


def _is_web_target_domain(parsed: SplitResult | None, domain: str) -> bool:
    if parsed is None:
        return False
    host = parsed.hostname or ""
    return (host == domain or host.endswith("." + domain)) and all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
        for label in host.split(".")
    )


def _is_taobao_target(parsed: SplitResult | None) -> bool:
    return any(
        _is_web_target_domain(parsed, domain) for domain in ("taobao.com", "tmall.com")
    )


def _is_taobao_login_target(parsed: SplitResult | None) -> bool:
    if not _is_taobao_target(parsed) or parsed is None:
        return False
    if parsed.hostname in {"login.taobao.com", "login.m.taobao.com", "login.tmall.com"}:
        return True
    path = re.sub(r"/+", "/", parsed.path.lower())
    return path == "/havanaone/login" or path.startswith("/havanaone/login/")


def _solver_request_scope_from_target_url(target_url: str) -> str:
    parsed = _split_web_target_url(target_url)
    if not _is_taobao_target(parsed) or parsed is None:
        return "unknown"
    path = re.sub(r"/+", "/", parsed.path.lower())
    if parsed.hostname == "sf-item.taobao.com" or "/sf_item/" in path:
        return "detail"
    if parsed.hostname == "sf.taobao.com" and "/list/" in path:
        return "seed"
    if "/punish" in path and "/list/" in path:
        return "seed"
    return "unknown"


def _normalize_solver_target_url(value: object) -> str:
    target_url = str(value or "").strip()
    if not target_url:
        return ""

    parsed = _split_web_target_url(target_url)
    if parsed is None:
        return target_url
    hostname = parsed.hostname or ""
    if hostname != "taobao.com" and not hostname.endswith(".taobao.com"):
        return target_url

    path = parsed.path
    punish_marker = "/_____tmd_____/punish"
    marker_index = path.lower().find(punish_marker)
    was_punish_url = marker_index >= 0
    if marker_index >= 0:
        path = path[:marker_index]
    while "//" in path:
        path = path.replace("//", "/")
    lowered_path = path.lower()
    if hostname == "sf-item.taobao.com" and re.fullmatch(
        r"/sf_item/\d+\.htm", lowered_path
    ):
        return urlunsplit((parsed.scheme or "https", parsed.netloc, path, "", ""))
    if hostname != "sf.taobao.com" or "/list/" not in lowered_path:
        return target_url

    source_query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query = [
        (key, source_query[key])
        for key in ("location_code", "st_param", "auction_start_seg", "page")
        if str(source_query.get(key) or "").strip()
    ]
    if was_punish_url or "__captcha_solver_bg" in source_query:
        query.append(("__captcha_solver_bg", "1"))
    return urlunsplit(
        (parsed.scheme or "https", parsed.netloc, path, urlencode(query), "")
    )
