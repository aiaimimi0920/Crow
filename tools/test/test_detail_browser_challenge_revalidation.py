"""A stale page in one stage must not block another fresh detail request."""

from types import SimpleNamespace

import pytest

from tools import live_batch_smoke as smoke

URL = "https://sf-item.taobao.com/sf_item/610925725633.htm"


@pytest.mark.parametrize(
    "old_url",
    [
        URL,
        "https://sf.taobao.com/list/50025969__2.htm",
        "https://sf-item.taobao.com/sf_item/999.htm",
    ],
)
@pytest.mark.parametrize("fresh_challenge", [False, True])
def test_old_challenge_is_revalidated_without_touching_operator_page(
    monkeypatch, old_url, fresh_challenge
):
    import playwright.sync_api

    events = []

    class ExistingPage:
        url = old_url

        def content(self):
            return "x5secdata=old"

        def bring_to_front(self):
            pytest.fail("must not focus the existing tab")

        def close(self):
            pytest.fail("must not close the existing tab")

    class Page:
        url = URL

        def goto(self, url, **kwargs):
            events.append("fresh_request")
            return SimpleNamespace(status=200)

        def close(self):
            events.append("close_fresh_page")

    page = Page()
    context = SimpleNamespace(
        pages=[ExistingPage()],
        new_page=lambda: page,
        new_cdp_session=lambda target: SimpleNamespace(
            detach=lambda: events.append("session_detach")
        ),
    )
    browser = SimpleNamespace(contexts=[context])

    class Playwright:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", Playwright)
    monkeypatch.setattr(smoke, "connect_browser_over_cdp", lambda *a: browser)
    monkeypatch.setattr(
        smoke, "detach_attached_cdp_browser", lambda b: events.append("detach")
    )
    monkeypatch.setattr(
        smoke, "configure_browser_identity_before_navigation", lambda *a, **k: None
    )
    html = "x5secdata=fresh" if fresh_challenge else '<input id="J_StartPrice">'
    monkeypatch.setattr(smoke, "_wait_for_detail_ready", lambda p: html)
    if fresh_challenge:
        with pytest.raises(smoke.DetailChallengeError, match="browser detail request"):
            smoke._fetch_detail_with_browser_attached(
                {"url": URL}, cdp_endpoint="http://fixture"
            )
    else:
        assert (
            smoke._fetch_detail_with_browser_attached(
                {"url": URL}, cdp_endpoint="http://fixture"
            )[3]
            == "browser_navigation"
        )
    assert events[0] == "fresh_request"
    assert events.count("session_detach") == 1
    assert ("close_fresh_page" in events) == (not fresh_challenge or old_url == URL)
    assert events[-1] == "detach"
