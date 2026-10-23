"""Browser backpressure must preserve known challenges and stop page churn."""

from types import SimpleNamespace

import pytest
import requests

from tools import browserless_seed_probe, live_batch_smoke, live_smoke_browser, seed_collector
from tools import seed_collector_wait, worker_lifecycle
from tools.cdp_background_page import BackgroundPageCapacityError
from tools.test.seed_collector_test_context import _make_repo

URL = "https://sf.taobao.com/list/50025969__2.htm?page=1"
CHALLENGE = "<html>请完成验证 _____tmd_____/punish</html>"


def capacity(*args, **kwargs):
    raise BackgroundPageCapacityError("private browser detail")


def config(tmp_path):
    return seed_collector.SeedCollectorConfig(
        job_key="capacity-test", province="", city="", district="",
        location_code="371602", category="50025969",
        sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:test"),
        max_page=83, cdp_endpoint="http://127.0.0.1:9224",
        output_dir=tmp_path, worker_id="capacity-test", max_runs=1,
        pages_per_run=20, page_delay_seconds=0, api_base_url="http://fixture/api",
    )


def http_page(url=URL):
    response = SimpleNamespace(text=CHALLENGE, url=url, status_code=200, raise_for_status=lambda: None)
    return SimpleNamespace(get=lambda *args, **kwargs: response)


@pytest.mark.parametrize("module", [live_batch_smoke, live_smoke_browser])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("login", [False, True])
def test_known_http_challenge_survives_capacity(monkeypatch, module, enabled, login):
    monkeypatch.setattr(module, "list_browser_fallback_enabled", lambda: True)
    monkeypatch.setattr(module, "fetch_browser_list_page", capacity)
    reports = []
    monkeypatch.setattr(module, "request_captcha_solver", lambda *a, **k: reports.append((a, k)))
    url = "https://login.taobao.com/login.htm" if login else URL
    result = module.fetch_list_page(
        http_page(url), cdp_endpoint="http://fixture", target_url=URL,
        user_agent="test", solver_enabled=enabled, api_base_url="http://fixture/api",
    )
    assert result == (CHALLENGE, url, 200, "http_cookie_challenge_browser_capacity")
    assert len(reports) == int(enabled)
    if enabled:
        assert reports[0][0] == ("http://fixture", URL)
        assert reports[0][1] == {"api_base_url": "http://fixture/api", "manual_only": login}


@pytest.mark.parametrize("known_challenge", [False, True])
def test_capacity_stops_cycle_without_exhausting_or_inserting(tmp_path, monkeypatch, known_challenge):
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(seed_collector, "_collection_pause_state_with_retry", lambda _: {})
    monkeypatch.setattr(seed_collector, "resolve_runtime_user_agent", lambda _: "test")
    monkeypatch.setattr(worker_lifecycle, "checkpoint", lambda _: True)
    calls = []

    def fetch(*args, **kwargs):
        calls.append(True)
        if known_challenge:
            return CHALLENGE, URL, 200, "http_cookie_challenge_browser_capacity"
        return capacity()

    monkeypatch.setattr(seed_collector, "fetch_list_page", fetch)
    try:
        result = seed_collector.run_seed_collector_loop(
            config(tmp_path), repository=repo, http_session=object(),
            browserless_seed_probe=browserless_seed_probe,
        )
        assert len(calls) == 1
        last = result["results"][-1]
        assert last["reason"] == ("list_challenge_page" if known_challenge else "browser_page_capacity")
        assert repo.seed_queue_counts()["seed_item_pending_detail"] == 0
        retry = repo.claim_seed_scan_page("retry", lease_seconds=30)
        assert retry and retry["page"] == 1
    finally:
        repo.engine.dispose()


def test_capacity_wait_does_not_use_auth_state_as_recovery(tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr(worker_lifecycle, "wait", waits.append)
    monkeypatch.setattr(seed_collector_wait, "fetch_json", lambda *a, **k: pytest.fail("auth is not capacity"))
    seed_collector_wait.wait_after_seed_run(
        config(tmp_path), [{"decision": "seed_collection_paused", "reason": "browser_page_capacity"}], 60,
    )
    assert waits == [60]


def test_failed_challenge_report_does_not_hide_http_evidence(monkeypatch):
    monkeypatch.setattr(live_smoke_browser, "list_browser_fallback_enabled", lambda: True)
    monkeypatch.setattr(live_smoke_browser, "fetch_browser_list_page", capacity)
    monkeypatch.setattr(live_smoke_browser, "request_captcha_solver", capacity)
    result = live_smoke_browser.fetch_list_page(
        http_page(), cdp_endpoint="http://fixture", target_url=URL,
        user_agent="test", solver_enabled=True,
    )
    assert result[0] == CHALLENGE


def test_capacity_after_recovery_does_not_report_same_challenge_twice(monkeypatch):
    module = live_smoke_browser
    monkeypatch.setattr(module, "list_browser_fallback_enabled", lambda: True)
    monkeypatch.setattr(module, "list_browser_recovery_max_attempts", lambda: 3)
    monkeypatch.setattr(module, "list_browser_recovery_wait_seconds", lambda: 0)
    calls, reports = [], []

    def fetch(*args):
        calls.append(True)
        return (CHALLENGE, URL) if len(calls) == 1 else capacity()

    monkeypatch.setattr(module, "fetch_browser_list_page", fetch)
    monkeypatch.setattr(module, "request_captcha_solver", lambda *a, **k: reports.append(True))
    result = module.fetch_list_page(
        http_page(), cdp_endpoint="http://fixture", target_url=URL,
        user_agent="test", solver_enabled=True,
    )
    assert result[0] == CHALLENGE
    assert len(calls) == 2 and len(reports) == 1


@pytest.mark.parametrize("module", [live_batch_smoke, live_smoke_browser])
def test_normal_http_payload_does_not_need_browser_capacity(monkeypatch, module):
    body = '<script id="sf-item-list-data">{"data":[]}</script>'
    response = SimpleNamespace(text=body, url=URL, status_code=200, raise_for_status=lambda: None)
    http = SimpleNamespace(get=lambda *a, **k: response)
    monkeypatch.setattr(module, "list_browser_fallback_enabled", lambda: True)
    monkeypatch.setattr(module, "fetch_browser_list_page", capacity)
    assert module.fetch_list_page(
        http, cdp_endpoint="http://fixture", target_url=URL, user_agent="test",
    ) == (body, URL, 200, "http_cookie")


@pytest.mark.parametrize("module", [live_batch_smoke, live_smoke_browser])
def test_capacity_after_http_transport_error_stays_capacity(monkeypatch, module):
    def unavailable(*args, **kwargs):
        raise requests.ConnectionError("private transport detail")

    monkeypatch.setattr(module, "list_browser_fallback_enabled", lambda: True)
    monkeypatch.setattr(module, "fetch_browser_list_page", capacity)
    with pytest.raises(BackgroundPageCapacityError):
        module.fetch_list_page(
            SimpleNamespace(get=unavailable), cdp_endpoint="http://fixture",
            target_url=URL, user_agent="test",
        )
