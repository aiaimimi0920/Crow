"""Own short, buffered CDP HTTP requests without adopting caller sessions."""

import logging

from tools.capture_budget import bounded_http_timeout, check_capture_budget

logger = logging.getLogger(__name__)


def request_cdp(session_factory, method, url, *, timeout_seconds):
    timeout_seconds = bounded_http_timeout(timeout_seconds)
    session = session_factory()
    try:
        session.trust_env = False
        # This session is single-use. Ask the peer not to keep its socket alive
        # while callers retain the buffered response for JSON/status inspection.
        session.headers["Connection"] = "close"
        # requests buffers the response by default; closing the session does not
        # invalidate its body, JSON, status, or headers returned to the caller.
        response = getattr(session, method)(url, timeout=timeout_seconds)
        check_capture_budget()
        return response
    finally:
        try:
            session.close()
        except Exception as error:  # noqa: BLE001 -- cleanup must not replace the request outcome
            logger.debug(
                "CDP HTTP session close unavailable (%s)", type(error).__name__
            )
