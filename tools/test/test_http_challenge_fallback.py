"""A browser fallback failure must not erase positive HTTP challenge evidence."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from tools import live_batch_smoke as smoke
from tools.cdp_background_page import BackgroundPageCapacityError

SEED = "https://sf.taobao.com/list/50025969__2.htm?page=1"
DETAIL = "https://sf-item.taobao.com/sf_item/3001.htm"
CHALLENGE = "<html>_____tmd_____/punish x5secdata=fixture</html>"


def http(status, url, body=CHALLENGE):
    response = requests.Response()
    response.status_code, response.url = status, url
    response._content = body.encode()
    response.encoding = "utf-8"
    return SimpleNamespace(get=lambda *a, **k: response)


@pytest.mark.parametrize("status", [200, 403, 429, 503])
@pytest.mark.parametrize("failure", [RuntimeError, requests.ConnectionError])
def test_seed_http_challenge_survives_browser_failure(monkeypatch, status, failure):
    report = Mock(return_value={"status": "deferred_to_node_solver"})
    fallback = Mock(side_effect=failure("synthetic-private-browser-error"))
    monkeypatch.setattr(smoke, "list_browser_fallback_enabled", lambda: True)
    monkeypatch.setattr(smoke, "request_captcha_solver", report)
    monkeypatch.setattr(smoke, "fetch_browser_list_page", fallback)
    result = smoke.fetch_list_page(
        http(status, SEED),
        cdp_endpoint="http://fixture",
        target_url=SEED,
        user_agent="fixture",
        solver_enabled=True,
        api_base_url="http://api.test/api",
    )
    assert result == (CHALLENGE, SEED, status, "http_cookie_challenge_browser_error")
    assert fallback.call_count == report.call_count == 1
    assert report.call_args.kwargs["api_base_url"] == "http://api.test/api"


def test_seed_disabled_solver_keeps_evidence_without_reporting(monkeypatch):
    report = Mock()
    monkeypatch.setattr(smoke, "list_browser_fallback_enabled", lambda: True)
    monkeypatch.setattr(smoke, "request_captcha_solver", report)
    monkeypatch.setattr(
        smoke, "fetch_browser_list_page", Mock(side_effect=RuntimeError)
    )
    result = smoke.fetch_list_page(
        http(200, SEED),
        cdp_endpoint="http://fixture",
        target_url=SEED,
        user_agent="fixture",
        solver_enabled=False,
    )
    assert result[0] == CHALLENGE
    report.assert_not_called()


@pytest.mark.parametrize("failure", [RuntimeError, BackgroundPageCapacityError])
def test_detail_http_challenge_survives_browser_failure(monkeypatch, failure):
    error = failure("synthetic-private-browser-error")
    monkeypatch.setattr(smoke, "detail_browser_fallback_enabled", lambda: True)
    monkeypatch.setattr(smoke, "fetch_detail_with_browser", Mock(side_effect=error))
    with pytest.raises(smoke.DetailChallengeError) as caught:
        smoke.fetch_detail_html(
            http(200, DETAIL),
            {"id": "3001", "url": DETAIL},
            {},
            cdp_endpoint="http://fixture",
            referer_url="https://sf.taobao.com/",
        )
    assert caught.value.challenge_url == DETAIL
    assert caught.value.__cause__ is error
    assert "synthetic-private" not in str(caught.value)


def test_seed_fallback_success_does_not_report_stale_http_challenge(monkeypatch):
    report = Mock()
    monkeypatch.setattr(smoke, "list_browser_fallback_enabled", lambda: True)
    monkeypatch.setattr(smoke, "request_captcha_solver", report)
    monkeypatch.setattr(smoke, "fetch_browser_list_page", lambda *a: ("healthy", SEED))
    result = smoke.fetch_list_page(
        http(200, SEED),
        cdp_endpoint="http://fixture",
        target_url=SEED,
        user_agent="fixture",
        solver_enabled=True,
    )
    assert result[0] == "healthy"
    report.assert_not_called()
