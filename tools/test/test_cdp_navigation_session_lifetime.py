"""A configured CDP session must remain owned through the first navigation."""

from types import SimpleNamespace

import pytest

from tools import live_smoke_browser as browser
from tools import live_smoke_cdp as cdp

TARGET = "https://sf-item.taobao.com/sf_item/123.htm"


def capture_fixture(monkeypatch, *, failure=None):
    events = []
    state = {"attached": False}

    class Session:
        def send(self, method, _params=None):
            events.append(method)
            if failure == "configuration" and method == "Emulation.setTimezoneOverride":
                raise RuntimeError("configuration failed")
            return {}

        def detach(self):
            events.append("session_detached")
            state["attached"] = False
            if failure == "detach":
                raise RuntimeError("No session with given id")

    class Page:
        url = TARGET

        def evaluate(self, _expression):
            assert state["attached"]
            return {
                "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152.0.0.0",
                "platform": "Win32",
                "uaPlatform": "Windows",
                "webdriver": False,
                "deviceMemory": 8,
                "language": "zh-CN",
            }

        def goto(self, _url, **_kwargs):
            assert state["attached"], (
                "Navigation started after CDP configuration was released"
            )
            events.append("navigate")
            if failure == "navigation":
                raise RuntimeError("navigation failed")
            return SimpleNamespace(status=200)

        def close(self):
            events.append("page_closed")

    page = Page()

    class Context:
        pages = ()

        def new_page(self):
            return page

        def new_cdp_session(self, target):
            assert target is page
            if failure == "creation":
                raise RuntimeError("session creation failed")
            state["attached"] = True
            events.append("session_attached")
            return Session()

    context = Context()
    attached = SimpleNamespace(contexts=[context])

    class Playwright:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def ready(_page):
        assert state["attached"], "Document readiness must use the configured session"
        events.append("document_ready")
        if failure == "readiness":
            raise RuntimeError("readiness failed")
        return "<html><body>Owned detail capture fixture</body></html>"

    monkeypatch.setattr("playwright.sync_api.sync_playwright", Playwright)
    monkeypatch.setattr(browser, "connect_browser_over_cdp", lambda *_a: attached)
    monkeypatch.setattr(
        browser,
        "detach_attached_cdp_browser",
        lambda *_a: events.append("browser_disconnected"),
    )
    monkeypatch.setattr(browser, "_wait_for_detail_ready", ready)
    monkeypatch.setattr(
        cdp, "_browser_identity_values", lambda *_a: ("configured UA", "152.0.0.0")
    )
    return events, state, context, page


@pytest.mark.parametrize("failure", [None, "detach"])
def test_detail_configuration_survives_navigation_and_document_readiness(
    monkeypatch, failure
):
    events, state, *_ = capture_fixture(monkeypatch, failure=failure)
    result = browser._fetch_detail_with_browser_attached(
        {"url": TARGET}, cdp_endpoint="http://cdp.test"
    )
    assert result[1] == TARGET and result[3] == "browser_navigation"
    assert (
        events.index("navigate")
        < events.index("document_ready")
        < events.index("session_detached")
    )
    assert events.count("session_detached") == 1 and not state["attached"]
    assert events[-2:] == ["page_closed", "browser_disconnected"]


@pytest.mark.parametrize(
    "failure", ["navigation", "configuration", "creation", "readiness"]
)
def test_detail_failure_releases_only_its_session_and_preserves_primary_error(
    monkeypatch, failure
):
    events, state, *_ = capture_fixture(monkeypatch, failure=failure)
    with pytest.raises(RuntimeError, match=failure):
        browser._fetch_detail_with_browser_attached(
            {"url": TARGET}, cdp_endpoint="http://cdp.test"
        )
    assert events.count("session_detached") == (0 if failure == "creation" else 1)
    assert not state["attached"]
    assert events[-2:] == ["page_closed", "browser_disconnected"]


def test_legacy_preflight_retains_its_default_temporary_session_cleanup(monkeypatch):
    events, state, context, page = capture_fixture(monkeypatch)
    identity = cdp.configure_browser_identity_before_navigation(
        context, page, cdp_endpoint="http://cdp.test"
    )
    assert identity["platform"] == "Win32"
    assert events.count("session_detached") == 1 and not state["attached"]


def test_caller_owned_session_is_not_detached_by_preflight(monkeypatch):
    from tools.browser_cdp_session import held_cdp_session

    events, state, context, page = capture_fixture(monkeypatch)
    with held_cdp_session(context, page) as session:
        identity = cdp.configure_browser_identity_before_navigation(
            context, page, cdp_endpoint="http://cdp.test", cdp_session=session
        )
        assert identity["platform"] == "Win32" and state["attached"]
        assert "session_detached" not in events
    assert events.count("session_detached") == 1 and not state["attached"]


def test_scoped_detach_failure_does_not_mask_the_operation_error(monkeypatch):
    from tools.browser_cdp_session import held_cdp_session

    events, state, context, page = capture_fixture(monkeypatch, failure="detach")
    with (
        pytest.raises(ValueError, match="primary operation failure"),
        held_cdp_session(context, page),
    ):
        raise ValueError("primary operation failure")
    assert events.count("session_detached") == 1 and not state["attached"]
