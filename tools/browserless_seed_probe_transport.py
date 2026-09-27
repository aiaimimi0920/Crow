"""Tool exports and live facade bindings for native CDP cookie transport."""

from collections.abc import Callable, Mapping
from functools import partial
from typing import cast

from src.cdp_cookie_transport import (
    CookieExporter,
    PlaywrightFactory,
    _cdp_reconnect_attempts,
    _cdp_reconnect_backoff_seconds,
    _cdp_websocket_cache_path,
    _export_cdp_cookies_via_playwright,
    _export_cdp_cookies_via_websocket,
    _load_cached_cdp_websocket,
    _resolve_cdp_endpoint,
    _resolve_cdp_websocket_for_cookie_export,
    _write_cached_cdp_websocket,
    cdp_endpoint_is_healthy,
    export_cdp_cookies,
    filter_cdp_cookies_to_origins,
    resolve_cdp_user_agent,
    rewrite_cdp_websocket_url,
)


def bind_transport(host: Mapping[str, object]) -> dict[str, object]:
    """Retain late facade replacement without cloning function globals."""
    return {
        "_export_cdp_cookies_via_playwright": partial(
            _export_cdp_cookies_via_playwright,
            playwright_provider=lambda: cast(
                PlaywrightFactory | None, host["sync_playwright"]
            ),
            endpoint_resolver=lambda endpoint: cast(
                Callable[[str], str], host["_resolve_cdp_endpoint"]
            )(endpoint),
            connect_timeout=lambda: cast(int, host["DEFAULT_CDP_CONNECT_TIMEOUT_MS"]),
        ),
        "export_cdp_cookies": partial(
            export_cdp_cookies,
            websocket_export=lambda endpoint, origins: cast(
                CookieExporter, host["_export_cdp_cookies_via_websocket"]
            )(endpoint, origins),
            playwright_export=lambda endpoint, origins: cast(
                CookieExporter, host["_export_cdp_cookies_via_playwright"]
            )(endpoint, origins),
            health_check=lambda endpoint: cast(
                Callable[[str], bool], host["cdp_endpoint_is_healthy"]
            )(endpoint),
        ),
    }


__all__ = (
    "_cdp_reconnect_attempts",
    "_cdp_reconnect_backoff_seconds",
    "_cdp_websocket_cache_path",
    "_export_cdp_cookies_via_playwright",
    "_export_cdp_cookies_via_websocket",
    "_load_cached_cdp_websocket",
    "_resolve_cdp_endpoint",
    "_resolve_cdp_websocket_for_cookie_export",
    "_write_cached_cdp_websocket",
    "cdp_endpoint_is_healthy",
    "export_cdp_cookies",
    "filter_cdp_cookies_to_origins",
    "resolve_cdp_user_agent",
    "rewrite_cdp_websocket_url",
)
