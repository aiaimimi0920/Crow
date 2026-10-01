"""Invalid page data must not masquerade as an unavailable browser transport."""

import json

import pytest

from src.collection.adapters import taobao_list_probe
from tools import (
    browserless_seed_probe,
    live_batch_smoke,
    live_smoke_browser,
    seed_collector,
    taobao_login_health,
)
from tools.test.seed_collector_test_context import _make_repo

LIST_URL = "https://sf.taobao.com/list/50025969__2.htm?page=1"
BROKEN_HTML = '<script id="sf-item-list-data">{"data":[{"title":"unfinished}</script>'
EMPTY_HTML = '<script id="sf-item-list-data">{"data":[]}</script>'


def _browser(monkeypatch, html, final_url=LIST_URL, error=None):
    target = {
        "id": "owned-list",
        "type": "page",
        "url": LIST_URL,
        "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/owned-list",
    }
    closed = []
    monkeypatch.setattr(taobao_login_health, "list_cdp_targets", lambda _: [])
    monkeypatch.setattr(
        taobao_login_health, "compact_cdp_pages_if_needed", lambda *a, **k: None
    )
    monkeypatch.setattr(taobao_login_health, "read_cdp_json", lambda *a, **k: target)
    monkeypatch.setattr(taobao_login_health, "activate_cdp_target", lambda *a: None)

    def evaluate(*args):
        if error is not None:
            raise error
        return {"result": {"result": {"value": {"html": html, "url": final_url}}}}

    monkeypatch.setattr(taobao_login_health, "evaluate_cdp_expression", evaluate)
    monkeypatch.setattr(
        taobao_login_health,
        "close_cdp_target",
        lambda _, target_id: closed.append(target_id),
    )
    return closed


@pytest.mark.parametrize("probe", [taobao_list_probe, browserless_seed_probe])
def test_summary_classifies_invalid_payload_but_extraction_still_fails(probe):
    summary = probe.summarize_list_page(BROKEN_HTML, final_url=LIST_URL)

    assert summary["has_script"] is False
    assert summary["item_count"] is None
    assert summary["payload_error"] == "invalid_json"
    assert summary["body_has_challenge"] is False
    assert summary["body_has_login"] is False
    with pytest.raises(json.JSONDecodeError):
        probe.extract_list_payload(BROKEN_HTML)


@pytest.mark.parametrize("module", [live_batch_smoke, live_smoke_browser])
@pytest.mark.parametrize(
    ("html", "final_url", "preserve"),
    [
        (BROKEN_HTML, LIST_URL, False),
        (EMPTY_HTML, LIST_URL, False),
        (BROKEN_HTML + "请完成验证", LIST_URL, True),
        (BROKEN_HTML, LIST_URL + "/_____tmd_____/punish", True),
        (BROKEN_HTML, "https://login.taobao.com/login.htm", True),
    ],
)
def test_navigation_does_not_confuse_payload_failure_with_cdp_failure(
    monkeypatch, module, html, final_url, preserve
):
    closed = _browser(monkeypatch, html, final_url)

    assert module.fetch_browser_navigation_list_page(
        "http://127.0.0.1:9224", LIST_URL
    ) == (
        html,
        final_url,
    )
    assert closed == ([] if preserve else ["owned-list"])


@pytest.mark.parametrize("module", [live_batch_smoke, live_smoke_browser])
@pytest.mark.parametrize(
    "error",
    [TimeoutError("transport timed out"), json.JSONDecodeError("wire JSON", "{", 1)],
)
def test_actual_transport_errors_keep_cdp_unreachable_classification(
    monkeypatch, module, error
):
    closed = _browser(monkeypatch, EMPTY_HTML, error=error)

    with pytest.raises(live_batch_smoke.CdpEndpointUnavailableError) as raised:
        module.fetch_browser_navigation_list_page("http://127.0.0.1:9224", LIST_URL)

    assert raised.value.__cause__ is error
    assert closed == ["owned-list"]


@pytest.mark.parametrize("html", [BROKEN_HTML, EMPTY_HTML])
def test_collector_requeues_bad_json_instead_of_pausing_or_completing(
    tmp_path, monkeypatch, html
):
    repo = _make_repo(tmp_path)
    _browser(monkeypatch, html)
    monkeypatch.setattr(
        seed_collector, "_collection_pause_state_with_retry", lambda _: {}
    )
    monkeypatch.setattr(seed_collector, "resolve_runtime_user_agent", lambda _: "test")

    def fetch(_http, *, cdp_endpoint, target_url, **kwargs):
        page, url = live_batch_smoke.fetch_browser_navigation_list_page(
            cdp_endpoint, target_url
        )
        return page, url, None, "browser_page"

    monkeypatch.setattr(seed_collector, "fetch_list_page", fetch)
    config = seed_collector.SeedCollectorConfig(
        job_key="test-list-json",
        province="山东省",
        city="滨州市",
        district="滨城",
        location_code="371602",
        category="50025969",
        sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
        max_page=83,
        cdp_endpoint="http://127.0.0.1:9224",
        output_dir=tmp_path,
        worker_id="seed-json-test",
    )
    try:
        summary = seed_collector.run_seed_collector_once(
            config,
            repository=repo,
            http_session=object(),
            browserless_seed_probe=browserless_seed_probe,
        )
        if html == BROKEN_HTML:
            assert summary["decision"] == "seed_page_retryable_failure"
            assert summary["reason"] == "exception"
            assert "JSONDecodeError" in summary["error"]
            assert "auth_probe" not in summary
            retry = repo.claim_seed_scan_page("seed-json-retry", lease_seconds=30)
            assert retry is not None and retry["page"] == 1
        else:
            assert summary["decision"] == "seed_page_collected"
            assert summary["item_count"] == 0
    finally:
        repo.engine.dispose()
