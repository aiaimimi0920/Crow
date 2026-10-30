"""Offline owned-page navigation failures with independently controlled DOM/URL."""

from types import SimpleNamespace

import pytest
from playwright.sync_api import Error
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tools import capture_budget as budget
from tools import live_batch_smoke as smoke
from tools.test.test_detail_http_error_challenge import CHALLENGE, URL


def navigation_fixture(
    monkeypatch,
    *,
    code="ERR_TIMED_OUT",
    url=URL,
    html=CHALLENGE,
    existing=False,
    after_read=None,
    read_error=None,
    navigate_seconds=0,
    read_seconds=0,
    navigation_error=None,
    detach_seconds=0,
    detach_error=None,
):
    events, timeouts = [], []
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock.now)
    error = navigation_error or (
        PlaywrightTimeoutError("Page.goto: Timeout 90000ms exceeded. SECRET")
        if code == "operation_timeout"
        else Error(f"Page.goto: net::{code} at {URL}?token=SECRET")
    )

    class Page:
        def __init__(self):
            self.url = url

        def goto(self, *_args, **_kwargs):
            events.append("navigate")
            clock.now += navigate_seconds
            raise error

        def locator(self, selector):
            assert selector == "html"
            return self

        def inner_html(self, *, timeout):
            events.append("read_owned")
            timeouts.append(timeout)
            clock.now += read_seconds
            if after_read:
                after_read(self, context)
            if read_error:
                raise read_error
            return html

        def close(self):
            events.append("close_owned")

    page = Page()
    borrowed = SimpleNamespace(
        url=URL,
        locator=lambda _: SimpleNamespace(inner_html=lambda **_: CHALLENGE),
        close=lambda: pytest.fail("must not close borrowed page"),
        bring_to_front=lambda: pytest.fail("must not focus borrowed page"),
    )

    def detach():
        events.append("session_detach")
        clock.now += detach_seconds
        if detach_error:
            raise detach_error

    context = SimpleNamespace(
        pages=[borrowed] if existing else [],
        new_page=lambda: page,
        new_cdp_session=lambda _: SimpleNamespace(detach=detach),
    )

    class Driver:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            events.append("driver_stop")

    monkeypatch.setattr("playwright.sync_api.sync_playwright", Driver)
    monkeypatch.setattr(
        smoke,
        "connect_browser_over_cdp",
        lambda *_: SimpleNamespace(contexts=[context]),
    )
    monkeypatch.setattr(
        smoke, "detach_attached_cdp_browser", lambda _: events.append("browser_detach")
    )
    monkeypatch.setattr(
        smoke, "configure_browser_identity_before_navigation", lambda *_, **__: None
    )
    monkeypatch.setattr(
        smoke,
        "_wait_for_detail_ready",
        lambda _: pytest.fail("no ready retry on error"),
    )
    capture = lambda: smoke._fetch_detail_with_browser_attached(
        {"url": URL}, cdp_endpoint="http://fixture"
    )
    return SimpleNamespace(
        capture=capture,
        events=events,
        timeouts=timeouts,
        error=error,
        clock=clock,
        page=page,
        context=context,
        borrowed=borrowed,
    )
