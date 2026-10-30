"""Navigation recovery must not weaken identity, deadlines or failure semantics."""

import json

import pytest
from playwright.sync_api import Error
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tools import capture_budget as budget
from tools import live_batch_smoke as smoke
from tools.detail_browser_capture_child import capture_reply
from tools.test.detail_navigation_challenge_fixtures import navigation_fixture
from tools.test.test_detail_http_error_challenge import CHALLENGE, DETAIL, URL


@pytest.mark.parametrize(
    "url",
    [
        "about:blank",
        "",
        "https://[invalid",
        URL.replace("3001", "9999"),
        "https://sf.taobao.com/list/500.htm",
        "https://login.taobao.com/member/login.jhtml",
        "https://example.test/sf_item/3001.htm",
        URL.replace("https:", "http:"),
        URL.replace("https://", "https://user:SECRET@"),
    ],
)
def test_unbound_page_is_not_read_or_promoted(monkeypatch, url):
    fixture = navigation_fixture(monkeypatch, url=url)
    with pytest.raises(Error) as caught:
        fixture.capture()
    assert caught.value is fixture.error
    assert "read_owned" not in fixture.events
    assert "close_owned" in fixture.events


@pytest.mark.parametrize(
    "html", ["", "<html>loading</html>", DETAIL, "<html>service unavailable</html>"]
)
def test_partial_or_ready_document_does_not_convert_navigation_failure_to_success(
    monkeypatch, html
):
    fixture = navigation_fixture(monkeypatch, html=html)
    with pytest.raises(Error) as caught:
        fixture.capture()
    assert caught.value is fixture.error
    assert fixture.events.count("read_owned") == 1
    assert "close_owned" in fixture.events


@pytest.mark.parametrize(
    "url", [URL.replace("3001", "9999"), "about:blank", "https://[invalid"]
)
def test_navigation_during_read_cannot_pair_old_challenge_with_new_target(
    monkeypatch, url
):
    fixture = navigation_fixture(
        monkeypatch, after_read=lambda page, _: setattr(page, "url", url)
    )
    with pytest.raises(Error) as caught:
        fixture.capture()
    assert caught.value is fixture.error
    assert "close_owned" in fixture.events


@pytest.mark.parametrize(
    "error",
    [Error("SECRET"), PlaywrightTimeoutError("SECRET"), RuntimeError("SECRET")],
)
def test_optional_read_error_keeps_original_navigation_failure_private(
    monkeypatch, error, caplog
):
    fixture = navigation_fixture(monkeypatch, read_error=error)
    reply = capture_reply(
        lambda *_, **__: fixture.capture(),
        {"seed": {}, "cdp_endpoint": "http://fixture"},
    )
    assert reply["kind"] == "error"
    assert reply["diagnostic"]["browser_code"] == "ERR_TIMED_OUT"
    assert "SECRET" not in json.dumps(reply) + caplog.text
    assert fixture.events.count("read_owned") == 1
    assert "close_owned" in fixture.events


@pytest.mark.parametrize(
    "code",
    [
        "ERR_PROXY_CONNECTION_FAILED",
        "ERR_TUNNEL_CONNECTION_FAILED",
        "ERR_CERT_DATE_INVALID",
        "ERR_ABORTED",
        "ERR_UNKNOWN",
    ],
)
def test_unselected_navigation_error_does_not_probe_or_hide_dependency_failure(
    monkeypatch, code
):
    fixture = navigation_fixture(monkeypatch, code=code)
    with pytest.raises(Error) as caught:
        fixture.capture()
    assert caught.value is fixture.error
    assert "read_owned" not in fixture.events


@pytest.mark.parametrize(
    "error", [TimeoutError("SECRET"), ValueError("SECRET"), KeyboardInterrupt()]
)
def test_non_playwright_error_and_navigation_cancellation_remain_unchanged(
    monkeypatch, error
):
    fixture = navigation_fixture(monkeypatch, navigation_error=error)
    with pytest.raises(type(error)) as caught:
        fixture.capture()
    assert caught.value is error
    assert "read_owned" not in fixture.events


@pytest.mark.parametrize("navigate_seconds,read_seconds", [(5, 0), (3, 2)])
def test_capture_deadline_takes_precedence_over_recovery(
    monkeypatch, navigate_seconds, read_seconds
):
    fixture = navigation_fixture(
        monkeypatch, navigate_seconds=navigate_seconds, read_seconds=read_seconds
    )
    with budget.capture_budget(5), pytest.raises(budget.CaptureBudgetExceeded):
        fixture.capture()
    assert fixture.events.count("read_owned") == (0 if navigate_seconds == 5 else 1)
    assert "close_owned" in fixture.events


def test_optional_read_is_bounded_by_remaining_budget(monkeypatch):
    fixture = navigation_fixture(monkeypatch, navigate_seconds=4)
    with budget.capture_budget(5), pytest.raises(smoke.DetailChallengeError):
        fixture.capture()
    assert fixture.timeouts == [1000]
    assert "close_owned" not in fixture.events


def test_detach_crossing_deadline_preserves_evidence_but_not_challenge_outcome(
    monkeypatch,
):
    fixture = navigation_fixture(monkeypatch, detach_seconds=5)
    with budget.capture_budget(5), pytest.raises(budget.CaptureBudgetExceeded):
        fixture.capture()
    assert "close_owned" not in fixture.events
    assert fixture.events[-2:] == ["browser_detach", "driver_stop"]


def test_detach_cancellation_preserves_the_already_verified_challenge(monkeypatch):
    fixture = navigation_fixture(monkeypatch, detach_error=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        fixture.capture()
    assert "close_owned" not in fixture.events


def test_read_cancellation_propagates_without_promotion(monkeypatch):
    fixture = navigation_fixture(monkeypatch, read_error=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        fixture.capture()
    assert "close_owned" in fixture.events
    assert fixture.events[-2:] == ["browser_detach", "driver_stop"]


def test_login_content_cannot_be_promoted_as_target_challenge(monkeypatch):
    fixture = navigation_fixture(
        monkeypatch,
        html=CHALLENGE
        + '<iframe src="https://login.taobao.com/member/login.jhtml"></iframe>',
    )
    monkeypatch.setattr(smoke, "is_login_page", lambda *_: True)
    with pytest.raises(Error) as caught:
        fixture.capture()
    assert caught.value is fixture.error


def test_lost_borrowed_duplicate_still_preserves_the_recovered_challenge(monkeypatch):
    fixture = navigation_fixture(
        monkeypatch, existing=True, after_read=lambda _, context: context.pages.clear()
    )
    with pytest.raises(smoke.DetailChallengeError):
        fixture.capture()
    assert "close_owned" not in fixture.events


@pytest.mark.parametrize(
    "url",
    [
        URL + "/_____tmd_____/punish?x5secdata=fixture",
        "https://susong-item.taobao.com/auction/3001.htm",
    ],
)
def test_existing_same_item_canonicalization_is_preserved(monkeypatch, url):
    fixture = navigation_fixture(monkeypatch, url=url)
    with pytest.raises(smoke.DetailChallengeError) as caught:
        fixture.capture()
    assert caught.value.challenge_url == url
    assert "close_owned" not in fixture.events
