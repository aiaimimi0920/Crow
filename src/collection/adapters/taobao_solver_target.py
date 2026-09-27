"""Preserve Taobao collection identity while removing stale solver challenge data."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _solver_request_scope_from_target_url(target_url: str) -> str:
    normalized = str(target_url or "").strip().lower()
    if not normalized:
        return "unknown"
    if "sf-item.taobao.com" in normalized or "/sf_item/" in normalized:
        return "detail"
    if "sf.taobao.com/list/" in normalized or "sf.taobao.com//list/" in normalized:
        return "seed"
    if "/punish" in normalized and "/list/" in normalized:
        return "seed"
    return "unknown"


def _normalize_solver_target_url(value: object) -> str:
    target_url = str(value or "").strip()
    if not target_url:
        return ""

    try:
        parsed = urlsplit(target_url)
    except ValueError:
        return target_url

    hostname = (parsed.hostname or "").lower()
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
