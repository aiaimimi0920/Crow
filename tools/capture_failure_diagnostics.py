"""Fixed capture failure labels; no exception text or remote payload is trusted."""

from tools.capture_browser_codes import navigation_error_code, safe_browser_code
from tools.capture_error_frames import capture_error_frames, safe_capture_frames
from tools.cdp_reconnect_health import CdpReconnectHealthUnavailable
from tools.live_smoke_context import CdpEndpointUnavailableError
from tools.safe_exception_diagnostics import safe_exception_details

_CATEGORIES = {
    "TimeoutError": "timeout",
    "BrowserError": "browser_error",
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


def capture_error_diagnostic(error, *, include_frames=False):
    # Playwright's timeout does not inherit Python's TimeoutError. Importing
    # the public exception type starts no driver; non-browser installs remain valid.
    diagnostic = safe_exception_details(error)
    if isinstance(error, CdpReconnectHealthUnavailable):
        diagnostic["endpoint_unhealthy"] = True
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    except ImportError:
        pass
    else:
        if isinstance(error, PlaywrightTimeoutError):
            diagnostic = {"type": "TimeoutError", "message": "timeout"}
        elif isinstance(error, PlaywrightError):
            diagnostic = {"type": "BrowserError", "message": "browser_error"}
            if include_frames:
                code = navigation_error_code(error)
                if code:
                    diagnostic["browser_code"] = code
    frames = capture_error_frames(error) if include_frames else []
    if frames:
        diagnostic["frames"] = frames
    return diagnostic


def _safe_diagnostic(value):
    if isinstance(value, dict):
        kind, message = value.get("type"), value.get("message")
        if isinstance(kind, str) and isinstance(message, str):
            category = _CATEGORIES.get(kind)
            # Existing safe diagnostics may append status/errno. Keep only the
            # fixed category; never echo a serialized suffix from the helper.
            if category is not None and message.split(" ", 1)[0] == category:
                diagnostic = {"type": kind, "message": category}
                if kind == "RuntimeError" and value.get("endpoint_unhealthy") is True:
                    diagnostic["endpoint_unhealthy"] = True
                code = safe_browser_code(value.get("browser_code"))
                if kind == "BrowserError" and code:
                    diagnostic["browser_code"] = code
                frames = safe_capture_frames(value.get("frames"))
                if frames:
                    diagnostic["frames"] = frames
                return diagnostic
    return {"type": "Exception", "message": "unexpected_error"}


class CaptureHelperError(RuntimeError):
    """The original error stays in the child; carry only its safe category."""

    def __init__(self, diagnostic):
        super().__init__("detail browser capture failed")
        self.diagnostic = _safe_diagnostic(diagnostic)


def is_capture_proxy_unavailable(error):
    """Only explicit proxy failures describe a shared dependency outage."""
    return (
        isinstance(error, CaptureHelperError)
        and error.diagnostic.get("type") == "BrowserError"
        and error.diagnostic.get("browser_code")
        in {"ERR_PROXY_CONNECTION_FAILED", "ERR_TUNNEL_CONNECTION_FAILED"}
    )


def is_capture_navigation_connection_closed(error):
    """Navigation failed; neither the peer that closed it nor an outage is proven."""
    return (
        isinstance(error, CaptureHelperError)
        and error.diagnostic.get("type") == "BrowserError"
        and error.diagnostic.get("browser_code") == "ERR_CONNECTION_CLOSED"
    )


def is_capture_navigation_timed_out(error):
    """Only the helper's explicit navigation code, not a generic operation timeout."""
    return (
        isinstance(error, CaptureHelperError)
        and error.diagnostic.get("type") == "BrowserError"
        and error.diagnostic.get("browser_code") == "ERR_TIMED_OUT"
    )


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
