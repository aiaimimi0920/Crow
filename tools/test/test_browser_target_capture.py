"""Both public collection stages must obey the same capture contract."""

from types import SimpleNamespace

import pytest

from tools import live_batch_smoke as smoke
from tools import live_smoke_browser
from tools.test.browser_capture_fixtures import install_owned_page_fixture

TARGETS = {
    "seed": "https://sf.taobao.com/list/50025969__2.htm?location_code=371602&page=1",
    "detail": "https://sf-item.taobao.com/sf_item/3001.htm",
}
PAYLOADS = {
    "seed": '<script id="sf-item-list-data">{"data":[]}</script>',
    "detail": '<html><input id="J_StartPrice" value="123"></html>',
}
CHALLENGE = "<html>x5secdata=fixture</html>"


def capture_fixture(
    monkeypatch, module, scope, *, old_url=None, fresh_html=None, transition=None
):
    install_owned_page_fixture(monkeypatch)
    events = []
    target = TARGETS[scope]

    class Existing:
        url = old_url or TARGETS["detail" if scope == "seed" else "seed"]

        def locator(self, _):
            return self

        def inner_html(self, *, timeout):
            events.append("old_read")
            assert 0 < timeout <= 5000
            return CHALLENGE

        def close(self):
            pytest.fail("must not close borrowed page")

        def bring_to_front(self):
            pytest.fail("must not focus borrowed page")

    old = Existing()

    class Page:
        url = target

        def goto(self, url, **kwargs):
            assert url == target and events[-1] == "configure"
            events.append("fresh_request")
            if transition:
                transition(old, context)
            return SimpleNamespace(status=200)

        def close(self):
            events.append("close_owned")

    page = Page()
    context = SimpleNamespace(
        pages=[old],
        new_page=lambda: page,
        new_cdp_session=lambda _: SimpleNamespace(
            detach=lambda: events.append("session_detach")
        ),
    )

    class Driver:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            events.append("driver_stop")

    monkeypatch.setattr("playwright.sync_api.sync_playwright", Driver)
    monkeypatch.setattr(
        module,
        "connect_browser_over_cdp",
        lambda *_: SimpleNamespace(contexts=[context]),
    )
    monkeypatch.setattr(
        module, "detach_attached_cdp_browser", lambda _: events.append("browser_detach")
    )
    monkeypatch.setattr(
        module,
        "configure_browser_identity_before_navigation",
        lambda *a, **k: events.append("configure"),
    )
    html = PAYLOADS[scope] if fresh_html is None else fresh_html
    monkeypatch.setattr(
        module,
        "_wait_for_list_ready" if scope == "seed" else "_wait_for_detail_ready",
        lambda _: html,
    )

    def capture():
        if scope == "seed":
            return module.fetch_browser_navigation_list_page("http://fixture", target)
        return module._fetch_detail_with_browser_attached(
            {"url": target}, cdp_endpoint="http://fixture"
        )

    return capture, events, page


@pytest.mark.parametrize("module", [smoke, live_smoke_browser])
@pytest.mark.parametrize("scope", TARGETS)
@pytest.mark.parametrize("same_target", [False, True])
def test_old_challenge_never_replaces_fresh_business_request(
    monkeypatch, module, scope, same_target
):
    capture, events, _ = capture_fixture(
        monkeypatch, module, scope, old_url=TARGETS[scope] if same_target else None
    )
    result = capture()
    assert result[0] == PAYLOADS[scope]
    assert events.count("fresh_request") == events.count("close_owned") == 1
    assert events.count("old_read") == int(same_target)
    assert events[-2:] == ["browser_detach", "driver_stop"]


@pytest.mark.parametrize("scope", TARGETS)
@pytest.mark.parametrize("same_target", [False, True])
@pytest.mark.parametrize("removed", [False, True])
def test_challenge_handoff_uses_same_live_duplicate_rule(
    monkeypatch, scope, same_target, removed
):
    capture, events, _ = capture_fixture(
        monkeypatch,
        smoke,
        scope,
        fresh_html=CHALLENGE,
        old_url=TARGETS[scope] if same_target else None,
        transition=(lambda _, context: context.pages.clear()) if removed else None,
    )
    if scope == "detail":
        with pytest.raises(smoke.DetailChallengeError):
            capture()
    else:
        assert capture()[0] == CHALLENGE
    assert ("close_owned" in events) == (same_target and not removed)


@pytest.mark.parametrize("scope", TARGETS)
@pytest.mark.parametrize("failure", ["blank", "wrong_target"])
def test_unconfirmed_payload_cannot_be_success(monkeypatch, scope, failure):
    capture, events, page = capture_fixture(
        monkeypatch,
        smoke,
        scope,
        fresh_html="<html></html>" if failure == "blank" else None,
    )
    if failure == "wrong_target":
        page.url = TARGETS["detail" if scope == "seed" else "seed"]
    with pytest.raises(RuntimeError, match="payload was not confirmed"):
        capture()
    assert events.count("close_owned") == 1


def test_seed_fetch_entry_does_not_short_circuit_on_cached_challenge(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "fetch_open_browser_list_page",
        lambda *a, **k: pytest.fail("stale DOM shortcut"),
    )
    monkeypatch.setattr(
        smoke,
        "fetch_browser_navigation_list_page",
        lambda *a: (PAYLOADS["seed"], TARGETS["seed"]),
    )
    assert (
        smoke.fetch_browser_list_page("http://fixture", TARGETS["seed"])[0]
        == PAYLOADS["seed"]
    )
