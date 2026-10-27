"""Only bounded, fixed phase labels may leave the capture child."""

import io
import json
import sys
import time

import pytest

from tools import detail_browser_capture as boundary


def test_progress_is_disabled_outside_child_session(capsys):
    from tools.capture_progress import mark_capture_stage

    mark_capture_stage("page_navigate")
    assert capsys.readouterr().err == ""


def test_latest_valid_phase_survives_noise_and_rejects_private_labels(monkeypatch):
    from tools.capture_progress import (
        capture_progress,
        mark_capture_stage,
        parse_capture_progress,
    )

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    started = time.monotonic()
    with capture_progress():
        mark_capture_stage("cdp_connect")
        mark_capture_stage("https://private?token=SECRET")
        mark_capture_stage("page_navigate")
    observed = time.monotonic()
    raw = ("SECRET\n" + stream.getvalue() + "untrusted SECRET\n").encode()
    progress = parse_capture_progress(raw, started_at=started, observed_at=observed)
    assert progress["stage"] == "page_navigate"
    assert 0 <= progress["stage_elapsed_seconds"] <= observed - started + 0.001
    assert "SECRET" not in json.dumps(progress)
    assert "SECRET" not in stream.getvalue()


@pytest.mark.parametrize(
    "raw",
    [
        None,
        b"",
        b"CROW_CAPTURE_PHASE:v1 SECRET 12.0\n",
        b"CROW_CAPTURE_PHASE:v1 page_close nan\n",
        b"CROW_CAPTURE_PHASE:v1 page_close inf\n",
        b"CROW_CAPTURE_PHASE:v1 page_close 9.0\n",
        b"CROW_CAPTURE_PHASE:v1 page_close 21.0\n",
        b"CROW_CAPTURE_PHASE:v1 page_close 12.0 SECRET\n",
        b"CROW_CAPTURE_PHASE:v1 page_close 12.0",
        "CROW_CAPTURE_PHASE:v1 page_close 12.0\n",
    ],
)
def test_malformed_stale_or_incomplete_marker_has_no_progress(raw):
    from tools.capture_progress import parse_capture_progress

    assert parse_capture_progress(raw, started_at=10.0, observed_at=20.0) == {}


def test_progress_parser_inspects_only_a_bounded_tail():
    from tools.capture_progress import parse_capture_progress

    raw = b"CROW_CAPTURE_PHASE:v1 page_close 12.0\n" + b"x" * 20_000
    assert parse_capture_progress(raw, started_at=10.0, observed_at=20.0) == {}


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_progress_accepts_both_platform_line_endings(newline):
    from tools.capture_progress import parse_capture_progress

    assert parse_capture_progress(
        b"CROW_CAPTURE_PHASE:v1 page_close 12.0" + newline,
        started_at=10.0,
        observed_at=20.0,
    ) == {"stage": "page_close", "stage_elapsed_seconds": 8.0}


def test_deadline_keeps_safe_phase_through_worker_error_boundary():
    from tools.capture_failure_diagnostics import capture_failure_summary
    from tools.capture_progress import CaptureDeadlineExceeded
    from tools.live_smoke_context import CdpEndpointUnavailableError

    error = CdpEndpointUnavailableError(
        "http://SECRET",
        "detail_browser_capture_deadline",
        CaptureDeadlineExceeded(
            {"stage": "existing_page_read", "stage_elapsed_seconds": 123.45678}
        ),
    )
    assert capture_failure_summary(error) == {
        "operation": "detail_browser_capture_deadline",
        "deadline_exceeded": True,
        "cause": {"type": "TimeoutError", "message": "timeout"},
        "stage": "existing_page_read",
        "stage_elapsed_seconds": 123.457,
    }


@pytest.mark.parametrize("stage", ["page_close", "driver_stop", "helper_import"])
def test_real_blocked_child_reports_phase_without_changing_cleanup(tmp_path, stage):
    from tools.capture_progress import CaptureDeadlineExceeded
    from tools.test.test_detail_capture_deadline import alive

    script = """
import json,os,sys,time
from pathlib import Path
from tools.capture_progress import capture_progress,mark_capture_stage
request=json.load(sys.stdin)
Path(request['receipt']).write_text(str(os.getpid()))
with capture_progress():
    mark_capture_stage(request['stage'])
    sys.stderr.write('token=SECRET\\n');sys.stderr.flush()
    time.sleep(60)
"""
    path = tmp_path / "blocked-helper.pid"
    with pytest.raises(CaptureDeadlineExceeded) as raised:
        boundary.run_capture_process(
            [sys.executable, "-B", "-c", script],
            json.dumps({"receipt": str(path), "stage": stage}).encode(),
            timeout_seconds=1,
        )
    assert path.exists()
    assert not alive(int(path.read_text()))
    assert raised.value.progress["stage"] == stage
    assert 0 <= raised.value.progress["stage_elapsed_seconds"] <= 1.2
    assert "SECRET" not in str(raised.value)


def test_driver_wrapper_records_exit_even_when_capture_fails(capsys):
    from contextlib import contextmanager

    from tools.capture_progress import capture_driver, capture_progress

    calls = []

    @contextmanager
    def factory():
        calls.append("enter")
        try:
            yield "driver"
        finally:
            calls.append("exit")

    with (
        capture_progress(),
        pytest.raises(ValueError, match="primary"),
        capture_driver(factory) as driver,
    ):
        assert driver == "driver"
        raise ValueError("primary")
    assert calls == ["enter", "exit"]
    stderr = capsys.readouterr().err
    assert "driver_start" in stderr and "driver_stop" in stderr


def test_windows_cleanup_does_not_suppress_job_close_failure():
    class Job:
        def close(self):
            raise RuntimeError("job close failed")

    class Process:
        def poll(self):
            return 0

        def communicate(self, **kwargs):
            return b"", b"diagnostic"

    with pytest.raises(RuntimeError, match="job close failed"):
        boundary._cleanup_windows_capture(
            Job(), Process(), deadline=time.monotonic() + 1
        )


@pytest.mark.parametrize(
    "seconds", [True, "SECRET", float("nan"), float("inf"), -1, 10**500]
)
def test_untrusted_progress_cannot_escape_summary_or_mask_failure(seconds):
    from tools.capture_progress import CaptureDeadlineExceeded

    error = CaptureDeadlineExceeded(
        {"stage": "page_close", "stage_elapsed_seconds": seconds}
    )
    assert error.progress == {}
    assert "SECRET" not in str(error)


def test_real_capture_path_emits_phases_without_changing_session_ownership(
    monkeypatch, capsys
):
    from tools import live_smoke_browser as browser
    from tools.capture_progress import capture_progress
    from tools.test.test_cdp_navigation_session_lifetime import TARGET, capture_fixture

    events, state, *_ = capture_fixture(monkeypatch)
    with capture_progress():
        result = browser._fetch_detail_with_browser_attached(
            {"url": TARGET}, cdp_endpoint="http://SECRET"
        )
    assert result[1] == TARGET and not state["attached"]
    assert events[-2:] == ["page_closed", "browser_disconnected"]
    stderr = capsys.readouterr().err
    phases = [line.split()[1] for line in stderr.splitlines()]
    assert phases == [
        "driver_start",
        "cdp_connect",
        "existing_pages",
        "page_create",
        "page_session",
        "page_configure",
        "page_navigate",
        "detail_ready",
        "page_session_detach",
        "page_close",
        "browser_detach",
        "driver_stop",
    ]
    assert "SECRET" not in stderr and TARGET not in stderr


def test_stage_reaches_worker_summary_without_changing_retry_budget(tmp_path):
    from tools.capture_progress import CaptureDeadlineExceeded
    from tools.live_smoke_context import CdpEndpointUnavailableError
    from tools.test.test_detail_capture_diagnostics import worker_failure

    error = CdpEndpointUnavailableError(
        "http://SECRET",
        "detail_browser_capture_deadline",
        CaptureDeadlineExceeded(
            {"stage": "driver_stop", "stage_elapsed_seconds": 101.25}
        ),
    )
    summary, _ = worker_failure(tmp_path, error)
    assert summary["capture_failure"]["stage"] == "driver_stop"
    assert summary["capture_failure"]["stage_elapsed_seconds"] == 101.25
    assert summary["reason"] == "detail_cdp_unreachable"
    assert summary["retry_budget_preserved"] is True
    assert "SECRET" not in json.dumps(summary)
