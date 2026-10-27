"""Owned capture work must not restart a full timeout after a slow connection."""

from types import SimpleNamespace

import pytest

from tools import capture_budget as budget
from tools.detail_browser_attached import capture_attached_detail


def fixture(
    monkeypatch,
    *,
    connect_seconds=0,
    read_seconds=0,
    configure_seconds=0,
    ready_seconds=0,
    navigation_seconds=0,
    navigation_error=None,
    close_error=None,
):
    clock = SimpleNamespace(now=0)
    events, timeouts = [], []
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock.now)

    class Page:
        url = "https://example.test/detail/1"

        def goto(self, _url, *, wait_until, timeout):
            events.append("navigate")
            timeouts.append(timeout)
            if navigation_error:
                raise navigation_error
            clock.now += min(navigation_seconds, timeout / 1000)
            if navigation_seconds > timeout / 1000:
                raise TimeoutError("bounded navigation fixture")
            return SimpleNamespace(status=200)

        def close(self):
            events.append("close_owned_page")
            if close_error:
                raise close_error

    class ExistingPage:
        url = "https://taobao.com/"

        def content(self):
            clock.now += read_seconds
            events.append("read_existing_page")
            return "existing fixture"

        def locator(self, selector):
            assert selector == "html"
            return self

        def inner_html(self, *, timeout):
            events.append(("existing_page_timeout", timeout))
            clock.now += min(read_seconds, timeout / 1000)
            if read_seconds > timeout / 1000:
                raise TimeoutError("unresponsive existing page")
            return "existing fixture"

        def close(self):
            pytest.fail("capture does not own the existing page")

    page = Page()

    def new_page():
        events.append("create_owned_page")
        return page

    context = SimpleNamespace(
        pages=[ExistingPage()] if read_seconds else [],
        new_page=new_page,
        new_cdp_session=lambda _page: SimpleNamespace(
            detach=lambda: events.append("session_detach")
        ),
    )
    browser = SimpleNamespace(contexts=[context])

    class Driver:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            events.append("driver_stop")

    monkeypatch.setattr("playwright.sync_api.sync_playwright", Driver)

    def connect(*_args):
        clock.now += connect_seconds
        return browser

    def configure(*_args, **_kwargs):
        clock.now += configure_seconds

    def ready(_page):
        events.append("ready")
        clock.now += ready_seconds
        return "<html>owned capture fixture</html>"

    def capture():
        return capture_attached_detail(
            {"url": page.url},
            cdp_endpoint="http://fixture",
            connect_browser=connect,
            detach_browser=lambda _browser: events.append("browser_detach"),
            is_login_target=lambda _url: False,
            is_challenge=lambda *_args: False,
            is_login=lambda *_args: False,
            challenge_error=RuntimeError,
            configure_page=configure,
            wait_for_detail=ready,
        )

    return capture, events, timeouts, clock


def test_navigation_uses_remaining_budget_after_connect_and_configuration(monkeypatch):
    capture, events, timeouts, _ = fixture(
        monkeypatch, connect_seconds=140, configure_seconds=5
    )
    with budget.capture_budget(175):
        assert capture()[3] == "browser_navigation"
    assert timeouts == [30000]
    assert events[-3:] == ["close_owned_page", "browser_detach", "driver_stop"]


@pytest.mark.parametrize("phase", ["read", "connect"])
def test_exhausted_unowned_work_does_not_create_another_page(monkeypatch, phase):
    capture, events, _, _ = fixture(monkeypatch, **{phase + "_seconds": 6})
    with budget.capture_budget(5), pytest.raises(budget.CaptureBudgetExceeded):
        capture()
    assert "create_owned_page" not in events
    assert events[-2:] == ["browser_detach", "driver_stop"]


@pytest.mark.parametrize("phase", ["configure", "ready"])
def test_exhausted_owned_work_still_closes_its_page(monkeypatch, phase):
    capture, events, _, _ = fixture(monkeypatch, **{phase + "_seconds": 6})
    with budget.capture_budget(5), pytest.raises(budget.CaptureBudgetExceeded):
        capture()
    assert ("navigate" in events) is (phase == "ready")
    assert events[-3:] == ["close_owned_page", "browser_detach", "driver_stop"]


def test_capture_without_budget_keeps_legacy_navigation_timeout(monkeypatch):
    capture, events, timeouts, _ = fixture(monkeypatch)
    assert capture()[3] == "browser_navigation"
    assert timeouts == [90000]
    assert events[-3:] == ["close_owned_page", "browser_detach", "driver_stop"]


@pytest.mark.parametrize(
    "primary",
    [
        ValueError("primary fixture"),
        TimeoutError("primary timeout"),
        KeyboardInterrupt(),
    ],
)
def test_cleanup_error_does_not_replace_navigation_failure_or_cancellation(
    monkeypatch, primary, caplog
):
    capture, events, _, _ = fixture(
        monkeypatch,
        navigation_error=primary,
        close_error=TimeoutError("private cleanup"),
    )
    with pytest.raises(type(primary)) as caught:
        capture()
    assert caught.value is primary
    assert "private cleanup" not in caplog.text
    assert events[-3:] == ["close_owned_page", "browser_detach", "driver_stop"]


def test_cleanup_failure_without_primary_is_not_silently_accepted(monkeypatch):
    failure = TimeoutError("cleanup fixture")
    capture, events, _, _ = fixture(monkeypatch, close_error=failure)
    with pytest.raises(TimeoutError) as caught:
        capture()
    assert caught.value is failure
    assert events[-3:] == ["close_owned_page", "browser_detach", "driver_stop"]


def test_slow_navigation_times_out_before_the_cleanup_reserve(monkeypatch):
    capture, events, timeouts, clock = fixture(
        monkeypatch, connect_seconds=140, configure_seconds=5, navigation_seconds=90
    )
    with budget.capture_budget(175), pytest.raises(TimeoutError):
        capture()
    assert timeouts == [30000]
    assert clock.now == 175
    assert "ready" not in events
    assert events[-3:] == ["close_owned_page", "browser_detach", "driver_stop"]


@pytest.mark.parametrize("deadline", [None, 175])
def test_unresponsive_existing_page_does_not_consume_the_capture_window(
    monkeypatch, deadline
):
    capture, events, _, clock = fixture(monkeypatch, read_seconds=180)
    with budget.capture_budget(deadline):
        assert capture()[3] == "browser_navigation"
    assert clock.now == 5
    assert ("existing_page_timeout", 5000) in events
    assert "read_existing_page" not in events


def test_existing_page_read_is_capped_by_remaining_operation_budget(monkeypatch):
    capture, events, _, clock = fixture(
        monkeypatch, connect_seconds=173, read_seconds=180
    )
    with budget.capture_budget(175), pytest.raises(budget.CaptureBudgetExceeded):
        capture()
    assert clock.now == 175
    assert ("existing_page_timeout", 2000) in events
    assert "create_owned_page" not in events
    assert events[-2:] == ["browser_detach", "driver_stop"]
