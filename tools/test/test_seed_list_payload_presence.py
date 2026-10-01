"""An HTTP success is not evidence that the source returned a complete list."""

import pytest

from tools import browserless_seed_probe, seed_collector
from tools.test.seed_collector_test_context import _make_repo

SHELL = "<html><head></head><body>loading</body></html>"
EMPTY = '<script id="sf-item-list-data">{"data":[]}</script>'
FILTERED = (
    '<script id="sf-item-list-data">'
    '{"data":[{"id":"2001","status":"failure","bidCount":0}]}</script>'
)


@pytest.mark.parametrize(
    "method", ["http_cookie", "browser_page", "browser_page_after_http_challenge"]
)
@pytest.mark.parametrize(
    "html", [SHELL, EMPTY, FILTERED], ids=["missing", "empty", "filtered"]
)
def test_only_a_valid_empty_list_can_finish_a_sort(tmp_path, monkeypatch, method, html):
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(
        seed_collector, "_collection_pause_state_with_retry", lambda _: {}
    )
    monkeypatch.setattr(seed_collector, "resolve_runtime_user_agent", lambda _: "test")
    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda _http, **kwargs: (html, kwargs["target_url"], 200, method),
    )
    if html == SHELL:

        def reject_write(*args, **kwargs):
            raise AssertionError(
                "A missing payload must not publish items or complete a page"
            )

        monkeypatch.setattr(repo, "upsert_seed_items", reject_write)
        monkeypatch.setattr(repo, "complete_seed_scan_page", reject_write)

    config = seed_collector.SeedCollectorConfig(
        job_key="payload-presence-test",
        province="山东省",
        city="滨州市",
        district="滨城",
        location_code="371602",
        category="50025969",
        sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
        max_page=83,
        cdp_endpoint="http://127.0.0.1:9224",
        output_dir=tmp_path,
        worker_id="payload-presence-test",
    )
    try:
        summary = seed_collector.run_seed_collector_once(
            config,
            repository=repo,
            http_session=object(),
            browserless_seed_probe=browserless_seed_probe,
        )
        retry = repo.claim_seed_scan_page("next-worker", lease_seconds=30)
        if html == SHELL:
            assert summary["decision"] == "seed_page_retryable_failure"
            assert summary["reason"] == (
                "browser_list_payload_missing"
                if method.startswith("browser_page")
                else "list_payload_missing"
            )
            assert "auth_probe" not in summary
            assert retry is not None and retry["page"] == 1
        else:
            assert summary["decision"] == "seed_page_collected"
            assert summary["item_count"] == 0
            assert summary["has_next"] is (html == FILTERED)
            if html == EMPTY:
                assert retry is None
            else:
                assert retry is not None and retry["page"] == 2
    finally:
        repo.engine.dispose()
