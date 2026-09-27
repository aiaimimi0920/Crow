"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.browserless_seed_probe_context import *
from src.collection.adapters.taobao_list_probe import (
    _looks_like_login_page,
    _site_boundary,
    build_navigation_headers,
    build_session_from_playwright_cookies,
    extract_list_payload,
    probe_seed_page,
    summarize_list_page,
)


def _format_local_datetime(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if abs(timestamp) >= 10**11:
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip()
    if not text:
        return ""
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None:
        if abs(numeric) >= 10**11:
            numeric /= 1000.0
        return datetime.fromtimestamp(numeric).strftime("%Y-%m-%d %H:%M:%S")
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return text


def build_userscript_like_batch_payload(payload: dict[str, Any], *, source_page_url: str) -> dict[str, Any]:
    raw_items = payload.get("data") if isinstance(payload.get("data"), list) else []
    items = []
    for item in raw_items:
        status = str(item.get("status", "")).lower()
        bid_count = item.get("bidCount", 0) or 0
        if status != "done" or bid_count < 1:
            continue
        latitude = item.get("latitude", item.get("lat"))
        longitude = item.get("longitude", item.get("lng"))
        items.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "currentPrice": item.get("currentPrice"),
                "initialPrice": item.get("initialPrice"),
                "auction_date": _format_local_datetime(item.get("end")),
                "auction_start_time": _format_local_datetime(item.get("startTime")),
                "end": item.get("end"),
                "url": normalize_seed_item_url(item.get("itemUrl")),
                "status": item.get("status"),
                "bidCount": bid_count,
                "bidderCount": item.get("bidUserNumber", item.get("bidderCount")),
                "applyCount": item.get("applyCount"),
                "watchCount": item.get("watchCount", item.get("pv")),
                "remindCount": item.get("remindCount", item.get("reminderCount")),
                "viewCount": item.get("viewCount", item.get("pv")),
                "location": item.get("itemAddress") or item.get("address") or item.get("location"),
                "full_address": item.get("itemAddress") or item.get("address") or item.get("location"),
                "district": item.get("district"),
                "city": item.get("city"),
                "latitude": latitude,
                "longitude": longitude,
                "coordinate_source": "list" if latitude is not None and longitude is not None else None,
                "auction_round": item.get("auctionRound", item.get("round")),
                "housing_type": item.get("housingType") or item.get("categoryName"),
                "deposit": item.get("deposit"),
                "is_processed": False,
            }
        )
    return {
        "items": items,
        "raw_payload": raw_items,
        "source_page_url": source_page_url,
    }


__all__ = (
    "_site_boundary",
    "build_navigation_headers",
    "build_session_from_playwright_cookies",
    "extract_list_payload",
    "_looks_like_login_page",
    "summarize_list_page",
    "_format_local_datetime",
    "build_userscript_like_batch_payload",
    "probe_seed_page",
)
