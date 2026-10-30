"""A completed helper failure retains safe locations, never browser error text."""

import json
from types import SimpleNamespace

import pytest

from tools import detail_browser_capture as boundary
from tools.capture_failure_diagnostics import (
    CaptureHelperError,
    capture_failure_summary,
)
from tools.detail_browser_capture_child import capture_reply
from tools.test.test_detail_capture_diagnostics import worker_failure


@pytest.mark.parametrize("browser_error", [False, True])
def test_actual_capture_failure_locations_survive_ipc_and_persistence(
    monkeypatch, tmp_path, browser_error
):
    import playwright.sync_api

    from tools.detail_browser_attached import capture_attached_detail

    events = []
    error_type = playwright.sync_api.Error if browser_error else AttributeError

    def navigate(*args, **kwargs):
        events.append("navigate")
        raise error_type("SECRET https://private/path?token=SECRET")

    page = SimpleNamespace(goto=navigate, close=lambda: events.append("page_close"))
    context = SimpleNamespace(
        pages=[],
        new_page=lambda: page,
        new_cdp_session=lambda page: SimpleNamespace(
            detach=lambda: events.append("session_detach")
        ),
    )

    class Driver:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("driver_stop")

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", Driver)

    def capture(seed, *, cdp_endpoint):
        return capture_attached_detail(
            seed,
            cdp_endpoint=cdp_endpoint,
            connect_browser=lambda *args: SimpleNamespace(contexts=[context]),
            detach_browser=lambda browser: events.append("browser_detach"),
            is_login_target=lambda url: False,
            is_challenge=lambda html, url: False,
            is_login=lambda html, url: False,
            challenge_error=AssertionError,
            configure_page=lambda *args, **kwargs: None,
            wait_for_detail=lambda page: pytest.fail("must not read after failure"),
        )

    reply = capture_reply(
        capture,
        {"seed": {"url": "https://fixture/item"}, "cdp_endpoint": "http://fixture"},
    )
    diagnostic = reply["diagnostic"]
    assert diagnostic["type"] == ("BrowserError" if browser_error else "Exception")
    assert diagnostic["message"] == (
        "browser_error" if browser_error else "unexpected_error"
    )
    assert any(
        frame["file"] == "tools/detail_browser_attached.py" and frame["line"] > 0
        for frame in diagnostic["frames"]
    )
    assert events == [
        "navigate",
        "session_detach",
        "page_close",
        "browser_detach",
        "driver_stop",
    ]
    with pytest.raises(CaptureHelperError) as raised:
        boundary.decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")
    summary, repository = worker_failure(tmp_path, raised.value)
    assert summary["capture_failure"]["cause"] == diagnostic
    assert summary["reason"] == "exception"
    assert "retry_budget_preserved" not in summary
    from src.storage.models import FapaiSeedItem

    with repository.session_factory() as session:
        assert session.get(FapaiSeedItem, "3001").detail_attempt_count == 1
    serialized = json.dumps(summary)
    assert "SECRET" not in serialized and "https://private" not in serialized
    saved = json.loads(
        (tmp_path / "detail_worker_summary.json").read_text(encoding="utf-8")
    )
    assert saved["capture_failure"]["cause"] == diagnostic


@pytest.mark.parametrize(
    "frames",
    [
        None,
        "SECRET",
        {},
        [None],
        [{"file": ["SECRET"], "line": 1}],
        [{"file": "C:/private/SECRET", "line": 1}],
        [{"file": "tools/detail_browser_attached.py", "line": True}],
        [{"file": "tools/detail_browser_attached.py", "line": "SECRET"}],
        [{"file": "tools/detail_browser_attached.py", "line": -1}],
        [{"file": "tools/detail_browser_attached.py", "line": 1_000_001}],
    ],
)
def test_untrusted_frame_values_are_not_serialized(frames):
    error = CaptureHelperError(
        {"type": "RuntimeError", "message": "runtime_error", "frames": frames}
    )
    assert capture_failure_summary(error)["cause"] == {
        "type": "RuntimeError",
        "message": "runtime_error",
    }


def test_frame_limit_and_unknown_fields_are_enforced_at_both_boundaries():
    from tools.capture_error_frames import safe_capture_frames

    frames = [
        {"file": "tools/detail_browser_attached.py", "line": line, "source": "SECRET"}
        for line in range(1, 25)
    ]
    expected = [
        {"file": "tools/detail_browser_attached.py", "line": line}
        for line in range(1, 9)
    ]
    assert safe_capture_frames(frames) == expected
    error = CaptureHelperError(
        {"type": "Exception", "message": "unexpected_error", "frames": frames}
    )
    assert capture_failure_summary(error)["cause"]["frames"] == expected
    assert "SECRET" not in json.dumps(capture_failure_summary(error))


def test_untrusted_filename_with_matching_basename_is_not_exposed(tmp_path):
    from tools.capture_failure_diagnostics import capture_error_diagnostic

    filename = tmp_path / "SECRET" / "tools" / "detail_browser_attached.py"

    def fail():
        raise RuntimeError("SECRET")

    fail.__code__ = fail.__code__.replace(co_filename=str(filename))
    try:
        fail()
    except RuntimeError as error:
        assert capture_error_diagnostic(error, include_frames=True) == {
            "type": "RuntimeError",
            "message": "runtime_error",
        }
    assert filename.name == "detail_browser_attached.py"


def test_frames_do_not_follow_exception_causes_or_capture_source_lines():
    from tools.capture_error_frames import capture_error_frames

    try:
        raise ValueError("SECRET")
    except ValueError as cause:
        try:
            raise RuntimeError("SECRET") from cause
        except RuntimeError as error:
            assert capture_error_frames(error) == []
