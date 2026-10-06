"""Detail Cookie export expands only the validated target, not all Taobao hosts."""

from contextlib import contextmanager
from functools import partial
from types import SimpleNamespace

import pytest

from src.cdp_cookie_transport import (
    DEFAULT_COOKIE_ORIGINS,
    filter_cdp_cookies_to_origins,
)

TARGET = "https://sf-item.taobao.com/sf_item/864933660682.htm"
ENDPOINT = "http://192.168.15.20:9224"


@pytest.mark.parametrize("detail_target", ["", TARGET])
def test_native_export_preserves_default_and_adds_exact_detail_url(
    monkeypatch, detail_target
):
    from src import cdp_cookie_transport, server

    cookies = [
        {"name": "session", "domain": ".taobao.com", "path": "/"},
        {"name": "seed", "domain": "sf.taobao.com", "path": "/"},
        {
            "name": "detail",
            "domain": "sf-item.taobao.com",
            "path": "/sf_item/864933660682.htm",
        },
        {"name": "other", "domain": "paimai.taobao.com", "path": "/"},
    ]
    calls = []

    def transport(endpoint, origins=DEFAULT_COOKIE_ORIGINS):
        calls.append((endpoint, tuple(origins)))
        return filter_cdp_cookies_to_origins(cookies, origins)

    monkeypatch.setattr(cdp_cookie_transport, "export_cdp_cookies", transport)
    result = server._export_auth_cdp_cookies(ENDPOINT, detail_target_url=detail_target)
    expected_origins = (
        (*DEFAULT_COOKIE_ORIGINS, TARGET) if detail_target else DEFAULT_COOKIE_ORIGINS
    )
    assert calls == [(ENDPOINT, expected_origins)]
    assert {cookie["name"] for cookie in result} == (
        {"session", "seed", "detail"} if detail_target else {"session", "seed"}
    )


@pytest.mark.parametrize(
    "target",
    [
        "https://example.invalid/",
        "https://sf.taobao.com/list/200782003__2.htm",
        "http://sf-item.taobao.com/sf_item/864933660682.htm",
        "https://user:password@sf-item.taobao.com/sf_item/864933660682.htm",
    ],
)
def test_native_export_rejects_untrusted_detail_before_transport(monkeypatch, target):
    from src import cdp_cookie_transport, server

    calls = []
    monkeypatch.setattr(
        cdp_cookie_transport,
        "export_cdp_cookies",
        lambda *args, **kwargs: calls.append(args),
    )
    with pytest.raises(ValueError):
        server._export_auth_cdp_cookies(ENDPOINT, detail_target_url=target)
    assert not calls


@pytest.mark.parametrize("detail_target", ["", TARGET])
def test_playwright_fallback_receives_full_detail_path(monkeypatch, detail_target):
    from src import cdp_cookie_transport as transport
    from src import server

    observed = []
    context = SimpleNamespace(cookies=lambda urls: observed.append(urls) or [])
    browser = SimpleNamespace(contexts=[context])
    chromium = SimpleNamespace(connect_over_cdp=lambda *_args, **_kwargs: browser)

    @contextmanager
    def provider():
        yield SimpleNamespace(chromium=chromium)

    def unavailable(*_args):
        raise OSError("synthetic websocket failure")

    monkeypatch.setattr(transport, "_export_cdp_cookies_via_websocket", unavailable)
    monkeypatch.setattr(
        transport,
        "_export_cdp_cookies_via_playwright",
        partial(
            transport._export_cdp_cookies_via_playwright,
            playwright_provider=lambda: provider,
            endpoint_resolver=lambda endpoint: endpoint,
        ),
    )
    assert (
        server._export_auth_cdp_cookies(ENDPOINT, detail_target_url=detail_target) == []
    )
    assert observed == [
        list(
            (*DEFAULT_COOKIE_ORIGINS, TARGET)
            if detail_target
            else DEFAULT_COOKIE_ORIGINS
        )
    ]
