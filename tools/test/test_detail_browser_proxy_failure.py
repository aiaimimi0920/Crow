"""A shared browser proxy outage is not a bad item or an authentication event."""

import json

import pytest

from src.storage.models import FapaiSeedItem
from tools import detail_worker
from tools.capture_failure_diagnostics import CaptureHelperError
from tools.detail_worker_wait import wait_after_detail_batch
from tools.test.test_detail_capture_diagnostics import worker_failure


def proxy_error(code="ERR_TUNNEL_CONNECTION_FAILED"):
    return CaptureHelperError(
        {"type": "BrowserError", "message": "browser_error", "browser_code": code}
    )


@pytest.mark.parametrize(
    "code", ["ERR_TUNNEL_CONNECTION_FAILED", "ERR_PROXY_CONNECTION_FAILED"]
)
def test_proxy_outage_preserves_item_budget_and_does_not_report_captcha(
    tmp_path, monkeypatch, code
):
    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda *a, **kw: pytest.fail("not a challenge"),
    )
    monkeypatch.setattr(
        detail_worker,
        "_build_cdp_unreachable_health",
        lambda *a: pytest.fail("CDP is not unreachable"),
    )
    summary, repository = worker_failure(tmp_path, proxy_error(code))
    assert summary["reason"] == "detail_browser_proxy_unavailable"
    assert summary["retry_budget_preserved"] is True
    assert summary["capture_failure"]["cause"]["browser_code"] == code
    assert "captcha_solver_report" not in summary and "cdp_health" not in summary
    with repository.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert row.status == "pending_detail"
        assert row.detail_attempt_count == 0
    saved = json.loads((tmp_path / "detail_worker_summary.json").read_text())
    assert saved["reason"] == summary["reason"]


@pytest.mark.parametrize(
    "code", ["ERR_ABORTED", "ERR_CONNECTION_RESET", "ERR_NAME_NOT_RESOLVED", "SECRET"]
)
def test_other_navigation_failures_do_not_gain_unlimited_item_retries(tmp_path, code):
    summary, repository = worker_failure(tmp_path, proxy_error(code))
    assert summary["reason"] == "exception"
    assert "retry_budget_preserved" not in summary
    with repository.session_factory() as session:
        assert session.get(FapaiSeedItem, "3001").detail_attempt_count == 1


def test_proxy_failure_breaks_batch_and_keeps_existing_cooldown(tmp_path, monkeypatch):
    loop = detail_worker
    from tools.test.detail_worker_test_context import _make_repo

    config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        max_attempts=30,
        target_success=10,
        cdp_endpoint="http://fixture",
        worker_id="proxy-batch",
        do_risk=False,
        challenge_cooldown_seconds=300,
        loop_interval_seconds=60,
        raw_only=True,
        llm_preflight_enabled=False,
    )
    result = {
        "decision": "detail_item_retryable_failure",
        "reason": "detail_browser_proxy_unavailable",
    }
    calls = []
    monkeypatch.setattr(
        loop, "run_detail_worker_once", lambda *a, **kw: calls.append(True) or result
    )
    monkeypatch.setattr(
        loop,
        "_detail_inter_item_delay_seconds",
        lambda *a, **kw: pytest.fail("must end batch"),
    )
    batch = loop.run_detail_worker_batch(
        config, repository=_make_repo(tmp_path), http_session=object(), browser_pages={}
    )
    assert calls == [True]
    assert batch["attempts"] == 1 and batch["completed"] == 0
    assert batch["retry_after_seconds"] == 300
    assert batch["reason_counts"] == {"detail_browser_proxy_unavailable": 1}
    assert loop._detail_batch_sleep_seconds(config, batch) == 300


def test_proxy_backoff_does_not_poll_auth_or_wake_early(tmp_path, monkeypatch):
    from tools import detail_worker_wait as wait_module

    config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        api_base_url="http://fixture/api",
        cdp_endpoint="http://fixture",
        target_success=1,
        max_attempts=1,
        worker_id="proxy-wait",
        do_risk=False,
    )
    waits = []
    monkeypatch.setattr(wait_module.worker_lifecycle, "wait", waits.append)
    monkeypatch.setattr(
        wait_module, "fetch_json", lambda *a, **kw: pytest.fail("not an auth wait")
    )
    result = {
        "results": [
            {
                "decision": "detail_item_retryable_failure",
                "reason": "detail_browser_proxy_unavailable",
            }
        ]
    }
    receipt = wait_after_detail_batch(config, result, 300)
    assert waits == [300]
    assert receipt["status_poll_count"] == 0
    assert receipt["wait_exit"] == "wait_returned"


def test_shared_item_can_recover_after_three_workers_observe_proxy_outage(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from tools.test.detail_worker_test_context import _make_repo, _seed_one_item

    repository = _make_repo(tmp_path)
    _seed_one_item(repository)
    config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://fixture",
        target_success=1,
        max_attempts=1,
        worker_id="proxy-1",
        do_risk=False,
        item_max_attempts=1,
        raw_only=True,
        solver_enabled=True,
        api_base_url="http://fixture/api",
    )
    monkeypatch.setattr(
        detail_worker, "_collection_pause_state_with_retry", lambda _: {"paused": False}
    )
    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda *a, **kw: pytest.fail("must not trigger solver"),
    )

    def fail(*args, **kwargs):
        raise proxy_error()

    for worker in range(1, 4):
        summary = detail_worker.run_detail_worker_once(
            replace(config, worker_id=f"proxy-{worker}"),
            repository=repository,
            http_session=object(),
            browser_pages={},
            process_item_func=fail,
        )
        assert summary["retry_budget_preserved"] is True
        assert "captcha_solver_report" not in summary

    def capture(*args, **kwargs):
        item_dir = tmp_path / "3001"
        item_dir.mkdir(exist_ok=True)
        (item_dir / "detail.html").write_text(
            "<html>fixture detail</html>", encoding="utf-8"
        )
        return {"fixture": True}

    recovered = detail_worker.run_detail_worker_once(
        config,
        repository=repository,
        http_session=object(),
        browser_pages={},
        process_item_func=capture,
    )
    assert recovered["decision"] == "detail_item_raw_captured"
    assert "retry_budget_preserved" not in recovered
