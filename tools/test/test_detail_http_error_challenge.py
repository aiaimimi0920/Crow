"""HTTP error status must not hide a positively identified detail challenge."""

import json
from types import SimpleNamespace

import pytest
import requests

from tools import live_batch_smoke as smoke
from tools.detail_browser_capture import decode_capture_reply
from tools.detail_browser_capture_child import capture_reply
from tools.test.test_detail_capture_diagnostics import worker_failure

URL = "https://sf-item.taobao.com/sf_item/3001.htm"
CHALLENGE = "<html>_____tmd_____/punish x5secdata=fixture</html>"
DETAIL = '<html><input id="J_StartPrice"></html>'


def attached_fixture(monkeypatch, status, html, *, existing_challenge=False):
    events = []
    page = SimpleNamespace(
        url=URL,
        goto=lambda *a, **kw: SimpleNamespace(status=status),
        close=lambda: events.append("close_owned_page"),
    )
    existing = SimpleNamespace(
        url=URL,
        locator=lambda _: SimpleNamespace(inner_html=lambda **kw: CHALLENGE),
        close=lambda: pytest.fail("must not close an existing page"),
        bring_to_front=lambda: pytest.fail("must not focus an existing page"),
    )
    context = SimpleNamespace(
        pages=[existing] if existing_challenge else [],
        new_page=lambda: page,
        new_cdp_session=lambda _: SimpleNamespace(
            detach=lambda: events.append("session_detach")
        ),
    )

    class Driver:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("driver_stop")

    monkeypatch.setattr("playwright.sync_api.sync_playwright", Driver)
    monkeypatch.setattr(
        smoke,
        "connect_browser_over_cdp",
        lambda *a: SimpleNamespace(contexts=[context]),
    )
    monkeypatch.setattr(
        smoke, "detach_attached_cdp_browser", lambda _: events.append("browser_detach")
    )
    monkeypatch.setattr(
        smoke, "configure_browser_identity_before_navigation", lambda *a, **kw: None
    )
    monkeypatch.setattr(smoke, "_wait_for_detail_ready", lambda _: html)
    return events


@pytest.mark.parametrize("status", [200, 403, 429, 503])
@pytest.mark.parametrize("existing_challenge", [False, True])
def test_browser_error_challenge_keeps_protocol_and_page_ownership(
    monkeypatch, status, existing_challenge
):
    events = attached_fixture(
        monkeypatch, status, CHALLENGE, existing_challenge=existing_challenge
    )
    reply = capture_reply(
        smoke._fetch_detail_with_browser_attached,
        {"seed": {"url": URL}, "cdp_endpoint": "http://fixture"},
    )
    assert reply == {
        "kind": "challenge",
        "operation": "browser detail request",
        "challenge_url": URL,
    }
    with pytest.raises(smoke.DetailChallengeError):
        decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")
    assert ("close_owned_page" in events) is existing_challenge
    assert events.count("session_detach") == 1
    assert events[-2:] == ["browser_detach", "driver_stop"]


@pytest.mark.parametrize("status", [403, 404, 429, 503])
def test_ordinary_browser_http_error_does_not_become_a_challenge(monkeypatch, status):
    events = attached_fixture(monkeypatch, status, "<html>service unavailable</html>")
    with pytest.raises(RuntimeError, match=f"returned HTTP {status}"):
        smoke._fetch_detail_with_browser_attached(
            {"url": URL}, cdp_endpoint="http://fixture"
        )
    assert events == [
        "session_detach",
        "close_owned_page",
        "browser_detach",
        "driver_stop",
    ]


def http_fixture(monkeypatch, status, html, *, fallback):
    response = requests.Response()
    response.status_code, response.url = status, URL
    response._content = html.encode("utf-8")
    response.encoding = "utf-8"
    monkeypatch.setattr(smoke, "detail_browser_fallback_enabled", lambda: fallback)
    calls = []
    fresh = (DETAIL, URL, len(DETAIL.encode("utf-8")), "browser_navigation")
    monkeypatch.setattr(
        smoke, "fetch_detail_with_browser", lambda *a, **kw: calls.append(True) or fresh
    )

    def fetch():
        return smoke.fetch_detail_html(
            SimpleNamespace(get=lambda *a, **kw: response),
            {"id": "3001", "url": URL},
            {},
            cdp_endpoint="http://fixture",
            referer_url="https://sf.taobao.com/",
            user_agent="fixture",
        )

    return fetch, calls, fresh


@pytest.mark.parametrize("status", [200, 403, 429, 503])
@pytest.mark.parametrize("fallback", [False, True])
def test_http_error_challenge_respects_existing_browser_fallback_policy(
    monkeypatch, status, fallback
):
    fetch, calls, fresh = http_fixture(
        monkeypatch, status, CHALLENGE, fallback=fallback
    )
    if fallback:
        assert fetch() == fresh and calls == [True]
    else:
        with pytest.raises(smoke.DetailChallengeError, match="HTTP detail request"):
            fetch()
        assert calls == []


@pytest.mark.parametrize("status", [403, 404, 429, 503])
@pytest.mark.parametrize("fallback", [False, True])
def test_ordinary_http_error_remains_http_error_without_browser_retry(
    monkeypatch, status, fallback
):
    fetch, calls, _ = http_fixture(
        monkeypatch, status, "<html>service unavailable</html>", fallback=fallback
    )
    with pytest.raises(requests.HTTPError) as caught:
        fetch()
    assert caught.value.response.status_code == status and calls == []


def test_non_error_detail_still_returns_http_capture(monkeypatch):
    fetch, calls, _ = http_fixture(monkeypatch, 200, DETAIL, fallback=True)
    assert fetch() == (DETAIL, URL, len(DETAIL.encode("utf-8")), "http_cookie")
    assert calls == []


def test_browser_error_challenge_reaches_worker_without_consuming_item_retry(
    monkeypatch, tmp_path
):
    from src.storage.models import FapaiSeedItem

    attached_fixture(monkeypatch, 403, CHALLENGE)
    reply = capture_reply(
        smoke._fetch_detail_with_browser_attached,
        {"seed": {"url": URL}, "cdp_endpoint": "http://fixture"},
    )
    with pytest.raises(smoke.DetailChallengeError) as caught:
        decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")
    summary, repository = worker_failure(tmp_path, caught.value)
    assert summary["reason"] == "detail_challenge_page"
    assert summary["retry_budget_preserved"] is True
    with repository.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert row.status == "pending_detail" and row.detail_attempt_count == 0
