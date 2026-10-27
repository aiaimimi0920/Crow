"""Fixed capture failure labels; no exception text or remote payload is trusted."""

from tools.live_smoke_context import CdpEndpointUnavailableError
from tools.safe_exception_diagnostics import safe_exception_details

_CATEGORIES = {
    "TimeoutError": "timeout",
    "HTTPError": "http_error",
    "ConnectionError": "connection_error",
    "JSONDecodeError": "invalid_json",
    "RequestError": "request_error",
    "OSError": "io_error",
    "ValueError": "invalid_value",
    "TypeError": "invalid_type",
    "LookupError": "lookup_error",
    "RuntimeError": "runtime_error",
    "Exception": "unexpected_error",
}
_OPERATIONS = frozenset(
    {
        "compact_cdp_page_targets",
        "connect_over_cdp",
        "connect_over_cdp_bounded_reconnect",
        "connect_over_cdp_capture_budget",
        "detail_browser_capture_deadline",
    }
)


def capture_error_diagnostic(error):
    # Playwright's timeout does not inherit Python's TimeoutError. Importing
    # the public exception type starts no driver; non-browser installs remain valid.
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    except ImportError:
        pass
    else:
        if isinstance(error, PlaywrightTimeoutError):
            return {"type": "TimeoutError", "message": "timeout"}
    return safe_exception_details(error)


def _safe_diagnostic(value):
    if isinstance(value, dict):
        kind, message = value.get("type"), value.get("message")
        if isinstance(kind, str) and isinstance(message, str):
            category = _CATEGORIES.get(kind)
            # Existing safe diagnostics may append status/errno. Keep only the
            # fixed category; never echo a serialized suffix from the helper.
            if category is not None and message.split(" ", 1)[0] == category:
                return {"type": kind, "message": category}
    return {"type": "Exception", "message": "unexpected_error"}


class CaptureHelperError(RuntimeError):
    """The original error stays in the child; carry only its safe category."""

    def __init__(self, diagnostic):
        super().__init__("detail browser capture failed")
        self.diagnostic = _safe_diagnostic(diagnostic)


def capture_failure_summary(error):
    """Supplement legacy failure reasons without changing retry classification."""
    if isinstance(error, CdpEndpointUnavailableError):
        operation = error.operation if error.operation in _OPERATIONS else "other"
        cause = error.cause
    elif isinstance(error, CaptureHelperError):
        operation, cause = "capture_helper", error
    else:
        return None
    diagnostic = (
        cause.diagnostic
        if isinstance(cause, CaptureHelperError)
        else capture_error_diagnostic(cause)
    )
    summary = {
        "operation": operation,
        "deadline_exceeded": operation == "detail_browser_capture_deadline",
        "cause": _safe_diagnostic(diagnostic),
    }
    if operation == "detail_browser_capture_deadline":
        from tools.capture_progress import (
            CaptureDeadlineExceeded,
            safe_capture_progress,
        )

        if isinstance(cause, CaptureDeadlineExceeded):
            summary.update(safe_capture_progress(cause.progress))
    return summary
