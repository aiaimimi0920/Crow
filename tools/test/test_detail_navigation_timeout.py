"""An explicit navigation timeout stops bulk consumption, not item retry limits."""

import json
from dataclasses import replace

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.storage.models import FapaiSeedItem
from tools import capture_failure_diagnostics as diagnostics
from tools import detail_worker
from tools.detail_browser_capture import decode_capture_reply
from tools.detail_browser_capture_child import capture_reply
from tools.test.detail_worker_test_context import _make_repo, _seed_items


def navigation_timeout():
    def navigate(*args, **kwargs):
        raise PlaywrightError("Page.goto: net::ERR_TIMED_OUT at https://fixture/SECRET")

    reply = capture_reply(navigate, {"seed": {}, "cdp_endpoint": "http://fixture"})
    with pytest.raises(diagnostics.CaptureHelperError) as raised:
        decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")
    return raised.value


def config(tmp_path):
    return detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://fixture",
        api_base_url="http://fixture/api",
        target_success=10,
        max_attempts=30,
        worker_id="timeout-1",
        do_risk=False,
        raw_only=True,
        solver_enabled=True,
        llm_preflight_enabled=False,
        item_max_attempts=1,
        challenge_cooldown_seconds=300,
        loop_interval_seconds=60,
    )


def test_explicit_navigation_timeout_survives_private_capture_protocol():
    error = navigation_timeout()
    assert diagnostics.is_capture_navigation_timed_out(error)
    assert error.diagnostic["browser_code"] == "ERR_TIMED_OUT"
    assert "SECRET" not in json.dumps(error.diagnostic)
    assert not diagnostics.is_capture_proxy_unavailable(error)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("Page.goto: net::ERR_TIMED_OUT"),
        TimeoutError("Page.goto: net::ERR_TIMED_OUT"),
        PlaywrightTimeoutError("Page.goto: net::ERR_TIMED_OUT"),
        PlaywrightError("Page.goto: net::ERR_TIMED_OUT"),
        diagnostics.CaptureHelperError(
            {"type": "BrowserError", "message": "browser_error"}
        ),
        diagnostics.CaptureHelperError(
            {
                "type": "TimeoutError",
                "message": "timeout",
                "browser_code": "ERR_TIMED_OUT",
            }
        ),
        diagnostics.CaptureHelperError(
            {
                "type": "BrowserError",
                "message": "invalid",
                "browser_code": "ERR_TIMED_OUT",
            }
        ),
        *[
            diagnostics.CaptureHelperError(
                {
                    "type": "BrowserError",
                    "message": "browser_error",
                    "browser_code": code,
                }
            )
            for code in ("ERR_CONNECTION_TIMED_OUT", "ERR_CONNECTION_CLOSED", "UNKNOWN")
        ],
    ],
)
def test_other_errors_do_not_activate_navigation_timeout_backoff(error):
    assert not diagnostics.is_capture_navigation_timed_out(error)


def test_navigation_timeout_ends_batch_before_claiming_other_items(
    tmp_path, monkeypatch
):
    repository = _make_repo(tmp_path)
    _seed_items(repository, ["3001", "3002", "3003"])
    calls = []
    monkeypatch.setattr(
        detail_worker, "_collection_pause_state_with_retry", lambda _: {"paused": False}
    )
    for name in ("_report_captcha_solver", "_build_cdp_unreachable_health"):
        monkeypatch.setattr(
            detail_worker,
            name,
            lambda *a, **kw: pytest.fail("not captcha or CDP outage"),
        )
    monkeypatch.setattr(
        detail_worker, "_detail_inter_item_delay_seconds", lambda *a, **kw: 0
    )

    def fail(*args, **kwargs):
        calls.append(True)
        raise navigation_timeout()

    active = config(tmp_path)
    result = detail_worker.run_detail_worker_batch(
        active,
        repository=repository,
        http_session=object(),
        browser_pages={},
        process_item_func=fail,
    )
    assert result["attempts"] == 1
    assert calls == [True]
    assert result["completed"] == 0
    assert result["claimed_items"] == result["process_item_calls"] == 1
    assert result["reason_counts"] == {"detail_navigation_timed_out": 1}
    assert result["challenge_break"] is True
    assert result["retry_after_seconds"] == 300
    assert detail_worker._detail_batch_sleep_seconds(active, result) == 300
    failure = result["results"][0]
    assert failure["reason"] == "detail_navigation_timed_out"
    assert "retry_budget_preserved" not in failure
    assert "captcha_solver_report" not in failure and "cdp_health" not in failure
    assert "SECRET" not in json.dumps(result)
    with repository.session_factory() as session:
        assert sorted(
            row.detail_attempt_count for row in session.query(FapaiSeedItem)
        ) == [
            0,
            0,
            1,
        ]


def test_shared_workers_cannot_exceed_original_item_attempt_limit(
    tmp_path, monkeypatch
):
    repository = _make_repo(tmp_path)
    _seed_items(repository, ["3001"])
    monkeypatch.setattr(
        detail_worker, "_collection_pause_state_with_retry", lambda _: {"paused": False}
    )
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise navigation_timeout()

    for worker in range(1, 4):
        result = detail_worker.run_detail_worker_once(
            replace(config(tmp_path), worker_id=f"timeout-{worker}"),
            repository=repository,
            http_session=object(),
            browser_pages={},
            process_item_func=fail,
        )
        assert result["decision"] == (
            "detail_item_retryable_failure" if worker == 1 else "detail_queue_empty"
        )
    assert calls == [True]
    with repository.session_factory() as session:
        assert session.get(FapaiSeedItem, "3001").detail_attempt_count == 1


@pytest.mark.parametrize("kind", [TimeoutError, PlaywrightTimeoutError])
def test_generic_timeout_keeps_existing_batch_policy(tmp_path, monkeypatch, kind):
    repository = _make_repo(tmp_path)
    _seed_items(repository, ["3001", "3002", "3003"])
    monkeypatch.setattr(
        detail_worker, "_collection_pause_state_with_retry", lambda _: {"paused": False}
    )
    monkeypatch.setattr(
        detail_worker, "_detail_inter_item_delay_seconds", lambda *a, **kw: 0
    )

    def fail(*args, **kwargs):
        reply = capture_reply(
            lambda **kw: (_ for _ in ()).throw(kind("SECRET")),
            {"seed": {}, "cdp_endpoint": "http://fixture"},
        )
        decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")

    result = detail_worker.run_detail_worker_batch(
        config(tmp_path),
        repository=repository,
        http_session=object(),
        browser_pages={},
        process_item_func=fail,
    )
    assert result["claimed_items"] == result["process_item_calls"] == 3
    assert result["reason_counts"] == {"exception": 3}
    assert result["challenge_break"] is False
    assert "SECRET" not in json.dumps(result)


def test_navigation_timeout_wait_is_cancellable_and_never_polls_auth(
    tmp_path, monkeypatch
):
    from tools import detail_worker_wait as wait_module

    calls = []

    class Stopping(BaseException):
        pass

    def stop(seconds):
        calls.append(seconds)
        raise Stopping()

    monkeypatch.setattr(wait_module.worker_lifecycle, "wait", stop)
    monkeypatch.setattr(
        wait_module, "fetch_json", lambda *a, **kw: pytest.fail("not an auth wait")
    )
    with pytest.raises(Stopping):
        wait_module.wait_after_detail_batch(
            config(tmp_path),
            {"results": [{"reason": "detail_navigation_timed_out"}]},
            300,
        )
    assert calls == [300]
