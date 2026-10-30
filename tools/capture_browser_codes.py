"""Fixed Chromium navigation codes, never free-form browser error messages."""

_CODES = frozenset(
    {
        "ERR_ABORTED",
        "ERR_ACCESS_DENIED",
        "ERR_ADDRESS_UNREACHABLE",
        "ERR_BLOCKED_BY_CLIENT",
        "ERR_BLOCKED_BY_ORB",
        "ERR_BLOCKED_BY_RESPONSE",
        "ERR_CERT_AUTHORITY_INVALID",
        "ERR_CERT_COMMON_NAME_INVALID",
        "ERR_CERT_DATE_INVALID",
        "ERR_CONNECTION_ABORTED",
        "ERR_CONNECTION_CLOSED",
        "ERR_CONNECTION_REFUSED",
        "ERR_CONNECTION_RESET",
        "ERR_CONNECTION_TIMED_OUT",
        "ERR_CONTENT_LENGTH_MISMATCH",
        "ERR_EMPTY_RESPONSE",
        "ERR_FAILED",
        "ERR_HTTP2_PROTOCOL_ERROR",
        "ERR_HTTP_RESPONSE_CODE_FAILURE",
        "ERR_INCOMPLETE_CHUNKED_ENCODING",
        "ERR_INTERNET_DISCONNECTED",
        "ERR_INVALID_RESPONSE",
        "ERR_INVALID_URL",
        "ERR_NAME_NOT_RESOLVED",
        "ERR_NETWORK_CHANGED",
        "ERR_PROXY_CONNECTION_FAILED",
        "ERR_SSL_PROTOCOL_ERROR",
        "ERR_TIMED_OUT",
        "ERR_TOO_MANY_REDIRECTS",
        "ERR_TUNNEL_CONNECTION_FAILED",
    }
)


def safe_browser_code(value):
    return value if isinstance(value, str) and value in _CODES else None


def navigation_error_code(error):
    # Called only for the public Playwright Error type. Inspect its bounded
    # first line, not call logs, URLs, exception causes, or arbitrary suffixes.
    message = error.message
    if not isinstance(message, str):
        return None
    header = message[:512].split("\n", 1)[0].rstrip("\r")
    prefix = "Page.goto: net::"
    if not header.startswith(prefix):
        return None
    return safe_browser_code(header[len(prefix) :].partition(" at ")[0])
