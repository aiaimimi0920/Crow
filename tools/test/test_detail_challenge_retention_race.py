"""A former duplicate cannot justify closing the only remaining challenge."""

from types import SimpleNamespace

import pytest

from tools import live_batch_smoke as smoke

URL = "https://sf-item.taobao.com/sf_item/3001.htm"
CHALLENGE = "<html>x5secdata=fixture</html>"
DETAIL = '<html><input id="J_StartPrice"></html>'


def capture_fixture(monkeypatch, transition, *, fresh_html=CHALLENGE):
    events = []

    class ExistingPage:
        url = URL
        html = CHALLENGE
        unreadable = False
        after_read = None

        def locator(self, selector):
            assert selector == "html"
            return self

        def inner_html(self, *, timeout):
            assert 0 < timeout <= 5000
            events.append("existing_read")
            events.append(("read_timeout", timeout))
            if self.unreadable:
                raise RuntimeError("synthetic stale page")
            if self.after_read and events.count("existing_read") == 2:
                self.after_read(self, context)
            return self.html

        def close(self):
            pytest.fail("borrowed page must not be closed")

        def bring_to_front(self):
            pytest.fail("borrowed page must not be focused")

    existing = ExistingPage()
    page = SimpleNamespace(
        url=URL,
        goto=lambda *a, **kw: SimpleNamespace(status=200),
        close=lambda: events.append("close_owned"),
    )
    context = SimpleNamespace(
        pages=[existing],
        new_page=lambda: page,
        new_cdp_session=lambda _: SimpleNamespace(
            detach=lambda: events.append("session_detach")
        ),
    )

    class Driver:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            events.append("driver_stop")

    def ready(_page):
        assert _page is page
        transition(existing, context)
        return fresh_html

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
        smoke, "configure_browser_identity_before_navigation", lambda *a, **kw: None
    )
    monkeypatch.setattr(smoke, "_wait_for_detail_ready", ready)
    return events


@pytest.mark.parametrize(
    "transition",
    [
        lambda old, context: context.pages.clear(),
        lambda old, _: setattr(old, "html", DETAIL),
        lambda old, _: setattr(old, "unreadable", True),
        lambda old, _: setattr(old, "url", URL.replace("3001", "9999")),
        lambda old, _: setattr(old, "url", "https://sf.taobao.com/list/500.htm"),
        lambda old, _: setattr(old, "url", "about:blank"),
        lambda old, _: setattr(old, "url", "https://[invalid"),
        lambda old, _: setattr(
            old, "url", "https://login.taobao.com/member/login.jhtml"
        ),
    ],
    ids=[
        "removed",
        "resolved",
        "unreadable",
        "other-detail",
        "seed",
        "blank",
        "malformed",
        "login",
    ],
)
def test_changed_borrowed_challenge_cannot_discard_new_challenge(
    monkeypatch, transition
):
    events = capture_fixture(monkeypatch, transition)
    with pytest.raises(smoke.DetailChallengeError, match="browser detail request"):
        smoke._fetch_detail_with_browser_attached(
            {"url": URL}, cdp_endpoint="http://fixture"
        )
    assert "close_owned" not in events
    assert events.count("session_detach") == 1
    assert events[-2:] == ["browser_detach", "driver_stop"]


@pytest.mark.parametrize("suffix", ["", "/_____tmd_____/punish?x5secdata=fixture"])
def test_still_live_same_target_challenge_retains_original_deduplication(
    monkeypatch, suffix
):
    events = capture_fixture(
        monkeypatch, lambda old, _: setattr(old, "url", URL + suffix)
    )
    with pytest.raises(smoke.DetailChallengeError):
        smoke._fetch_detail_with_browser_attached(
            {"url": URL}, cdp_endpoint="http://fixture"
        )
    assert events.count("close_owned") == 1
    assert events.count("existing_read") == 2


def test_healthy_new_capture_does_not_reinspect_borrowed_challenge(monkeypatch):
    events = capture_fixture(monkeypatch, lambda *_: None, fresh_html=DETAIL)
    result = smoke._fetch_detail_with_browser_attached(
        {"url": URL}, cdp_endpoint="http://fixture"
    )
    assert result[0] == DETAIL
    assert events.count("existing_read") == events.count("close_owned") == 1


@pytest.mark.parametrize("change", ["removed", "navigated"])
def test_borrowed_page_changing_during_recheck_is_not_a_live_duplicate(
    monkeypatch, change
):
    def changed(old, context):
        if change == "removed":
            context.pages.clear()
        else:
            old.url = URL.replace("3001", "9999")

    events = capture_fixture(
        monkeypatch, lambda old, _: setattr(old, "after_read", changed)
    )
    with pytest.raises(smoke.DetailChallengeError):
        smoke._fetch_detail_with_browser_attached(
            {"url": URL}, cdp_endpoint="http://fixture"
        )
    assert "close_owned" not in events
    assert events.count("existing_read") == 2


def test_duplicate_recheck_uses_original_budget_and_keeps_challenge_on_expiry(
    monkeypatch,
):
    from tools import capture_budget as budget

    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock.now)

    def transition(old, _):
        clock.now = 3
        old.after_read = lambda *_: setattr(clock, "now", 5)

    events = capture_fixture(monkeypatch, transition)
    with budget.capture_budget(5), pytest.raises(budget.CaptureBudgetExceeded):
        smoke._fetch_detail_with_browser_attached(
            {"url": URL}, cdp_endpoint="http://fixture"
        )
    assert "close_owned" not in events
    assert ("read_timeout", 2000) in events
    assert events[-2:] == ["browser_detach", "driver_stop"]


def test_recheck_cancellation_propagates_without_closing_either_challenge(monkeypatch):
    def cancel(*_):
        raise KeyboardInterrupt()

    events = capture_fixture(
        monkeypatch, lambda old, _: setattr(old, "after_read", cancel)
    )
    with pytest.raises(KeyboardInterrupt):
        smoke._fetch_detail_with_browser_attached(
            {"url": URL}, cdp_endpoint="http://fixture"
        )
    assert "close_owned" not in events
    assert events[-2:] == ["browser_detach", "driver_stop"]
