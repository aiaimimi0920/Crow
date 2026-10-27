"""Safe capture failure categories survive child IPC and worker summaries."""

import json

import pytest

from src.storage.models import FapaiSeedItem
from tools import detail_browser_capture as boundary
from tools import detail_worker
from tools.detail_browser_capture_child import capture_reply
from tools.live_smoke_context import CdpEndpointUnavailableError
from tools.test.detail_worker_test_context import _make_repo, _seed_one_item


def worker_failure(tmp_path, error):
    repository = _make_repo(tmp_path)
    _seed_one_item(repository)
    calls = []

    def process(*args, **kwargs):
        calls.append(True)
        raise error

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://fixture",
            target_success=1,
            max_attempts=1,
            worker_id="capture-diagnostic-test",
            do_risk=False,
        ),
        repository=repository,
        http_session=object(),
        browser_pages={},
        process_item_func=process,
    )
    assert calls == [True]
    return summary, repository


def test_total_deadline_is_distinguishable_without_changing_retry_policy(tmp_path):
    error = CdpEndpointUnavailableError(
        "http://fixture/private?token=SECRET",
        "detail_browser_capture_deadline",
        TimeoutError("body or cleanup SECRET"),
    )
    summary, repository = worker_failure(tmp_path, error)
    assert summary["capture_failure"] == {
        "operation": "detail_browser_capture_deadline",
        "deadline_exceeded": True,
        "cause": {"type": "TimeoutError", "message": "timeout"},
    }
    assert summary["reason"] == "detail_cdp_unreachable"
    assert summary["retry_budget_preserved"] is True
    with repository.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert row.status == "pending_detail"
        assert row.detail_attempt_count == 0
    assert "SECRET" not in json.dumps(summary)


@pytest.mark.parametrize("playwright_timeout", [False, True])
def test_transport_cause_is_not_lost_at_the_child_boundary(
    tmp_path, playwright_timeout
):
    timeout_class = TimeoutError
    if playwright_timeout:
        from playwright.sync_api import TimeoutError as timeout_class

    def capture(*args, **kwargs):
        raise CdpEndpointUnavailableError(
            "http://fixture",
            "connect_over_cdp_bounded_reconnect",
            timeout_class("SECRET"),
        )

    reply = capture_reply(capture, {"seed": {}, "cdp_endpoint": "http://fixture"})
    assert reply["diagnostic"] == {"type": "TimeoutError", "message": "timeout"}
    with pytest.raises(CdpEndpointUnavailableError) as raised:
        boundary.decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")
    summary, _ = worker_failure(tmp_path, raised.value)
    assert summary["capture_failure"] == {
        "operation": "connect_over_cdp_bounded_reconnect",
        "deadline_exceeded": False,
        "cause": {"type": "TimeoutError", "message": "timeout"},
    }


def test_helper_failure_keeps_safe_category_without_raw_exception(tmp_path):
    def capture(*args, **kwargs):
        raise ValueError("SECRET https://private/path")

    reply = capture_reply(capture, {"seed": {}, "cdp_endpoint": "http://fixture"})
    with pytest.raises(RuntimeError) as raised:
        boundary.decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")
    summary, repository = worker_failure(tmp_path, raised.value)
    assert summary["capture_failure"] == {
        "operation": "capture_helper",
        "deadline_exceeded": False,
        "cause": {"type": "ValueError", "message": "invalid_value"},
    }
    assert summary["reason"] == "exception"
    assert "retry_budget_preserved" not in summary
    with repository.session_factory() as session:
        assert session.get(FapaiSeedItem, "3001").detail_attempt_count == 1
    assert "SECRET" not in json.dumps(summary)


@pytest.mark.parametrize(
    "diagnostic",
    [
        None,
        [],
        "SECRET",
        {"type": ["SECRET"]},
        {"type": "SECRET", "message": "SECRET"},
        {"type": "TimeoutError", "message": "SECRET"},
    ],
)
def test_untrusted_or_old_reply_diagnostic_fails_closed(diagnostic):
    from tools.capture_failure_diagnostics import capture_failure_summary

    reply = {"kind": "cdp", "operation": "SECRET", "diagnostic": diagnostic}
    with pytest.raises(CdpEndpointUnavailableError) as raised:
        boundary.decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")
    assert capture_failure_summary(raised.value) == {
        "operation": "other",
        "deadline_exceeded": False,
        "cause": {"type": "Exception", "message": "unexpected_error"},
    }


def test_non_capture_errors_do_not_get_capture_metadata():
    from tools.capture_failure_diagnostics import capture_failure_summary

    assert capture_failure_summary(ValueError("SECRET")) is None


def test_legacy_reply_without_diagnostic_remains_readable():
    from tools.capture_failure_diagnostics import capture_failure_summary

    with pytest.raises(CdpEndpointUnavailableError) as raised:
        boundary.decode_capture_reply(
            '{"kind":"cdp","operation":"connect_over_cdp"}',
            cdp_endpoint="http://fixture",
        )
    assert capture_failure_summary(raised.value)["cause"] == {
        "type": "Exception",
        "message": "unexpected_error",
    }


def test_serialized_diagnostic_suffix_is_not_copied():
    from tools.capture_failure_diagnostics import (
        CaptureHelperError,
        capture_failure_summary,
    )

    error = CaptureHelperError(
        {"type": "HTTPError", "message": "http_error status=SECRET"}
    )
    assert capture_failure_summary(error)["cause"] == {
        "type": "HTTPError",
        "message": "http_error",
    }
