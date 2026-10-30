"""Only fixed browser failure codes cross the private capture boundary."""

import json

import pytest
from playwright.sync_api import Error, TimeoutError

from tools.capture_failure_diagnostics import (
    CaptureHelperError,
    capture_error_diagnostic,
    capture_failure_summary,
)
from tools.detail_browser_capture import decode_capture_reply
from tools.detail_browser_capture_child import capture_reply


@pytest.mark.parametrize(
    "code", ["ERR_ABORTED", "ERR_CONNECTION_RESET", "ERR_HTTP_RESPONSE_CODE_FAILURE"]
)
def test_navigation_code_survives_child_reply_and_summary_without_raw_text(code):
    def fail(*args, **kwargs):
        raise Error(
            f"Page.goto: net::{code} at https://private/?key=SECRET\nCall log: SECRET"
        )

    reply = capture_reply(fail, {"seed": {}, "cdp_endpoint": "http://fixture"})
    assert reply["diagnostic"]["browser_code"] == code
    with pytest.raises(CaptureHelperError) as raised:
        decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")
    summary = capture_failure_summary(raised.value)
    assert summary["cause"]["browser_code"] == code
    assert summary["cause"]["type"] == "BrowserError"
    assert "SECRET" not in json.dumps(summary)
    assert "https://private" not in json.dumps(reply)


@pytest.mark.parametrize(
    "message",
    [
        "Page.goto: net::ERR_SECRET at https://private/",
        "Page.goto: net::ERR_ABORTED_SECRET at https://private/",
        "Page.goto: SECRET net::ERR_ABORTED at https://private/",
        "Page.goto: failed at https://private/?reason=net::ERR_ABORTED",
        "Page.goto: unknown\nCall log: net::ERR_ABORTED",
        "Page.evaluate: net::ERR_ABORTED at https://private/",
        "SECRET " * 1000 + "Page.goto: net::ERR_ABORTED",
    ],
)
def test_unknown_or_embedded_codes_are_not_trusted(message):
    assert capture_error_diagnostic(Error(message), include_frames=True) == {
        "type": "BrowserError",
        "message": "browser_error",
    }


def test_existing_diagnostics_and_non_browser_failures_are_unchanged():
    message = "Page.goto: net::ERR_ABORTED at https://private/?SECRET"
    assert "browser_code" not in capture_error_diagnostic(Error(message))
    assert "browser_code" not in capture_error_diagnostic(
        RuntimeError(message), include_frames=True
    )
    assert capture_error_diagnostic(TimeoutError(message), include_frames=True) == {
        "type": "TimeoutError",
        "message": "timeout",
    }


@pytest.mark.parametrize("value", [None, True, [], {}, "SECRET", "ERR_ABORTED SECRET"])
def test_ipc_receiver_rejects_untrusted_code(value):
    summary = capture_failure_summary(
        CaptureHelperError(
            {"type": "BrowserError", "message": "browser_error", "browser_code": value}
        )
    )
    assert summary["cause"] == {"type": "BrowserError", "message": "browser_error"}


def test_ipc_receiver_does_not_add_codes_to_other_error_kinds():
    error = CaptureHelperError(
        {
            "type": "RuntimeError",
            "message": "runtime_error",
            "browser_code": "ERR_ABORTED",
        }
    )
    assert capture_failure_summary(error)["cause"] == {
        "type": "RuntimeError",
        "message": "runtime_error",
    }
