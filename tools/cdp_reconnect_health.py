"""Evidence of a failed endpoint probe, separate from page/driver timeouts."""

from urllib.parse import urlsplit

import requests


class CdpReconnectHealthUnavailable(RuntimeError):
    """A reconnect was skipped because the endpoint health probe failed."""


def cdp_metadata_recovered(endpoint: str, *, timeout_seconds: float) -> bool:
    """Read browser metadata only; do not attach, create pages or visit the site."""
    try:
        if urlsplit(endpoint).scheme not in {"http", "https"} or timeout_seconds <= 0:
            return False
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(
                endpoint.rstrip("/") + "/json/version",
                timeout=timeout_seconds,
                allow_redirects=False,
            )
            if response.status_code != 200:
                return False
            payload = response.json()
        websocket = (
            payload.get("webSocketDebuggerUrl") if isinstance(payload, dict) else None
        )
        if not isinstance(websocket, str):
            return False
        parsed = urlsplit(websocket)
        return bool(
            parsed.scheme in {"ws", "wss"}
            and parsed.hostname
            and parsed.path.startswith("/devtools/browser/")
            and parsed.path != "/devtools/browser/"
        )
    except (requests.RequestException, ValueError, OSError):
        return False


def batch_has_cdp_outage(result: dict) -> bool:
    """Legacy/ambiguous records retain their original backoff."""
    for item in result.get("results") or []:
        if (
            not isinstance(item, dict)
            or item.get("decision") != "detail_item_retryable_failure"
        ):
            continue
        failure = item.get("capture_failure")
        if item.get("reason") != "detail_cdp_unreachable" or not isinstance(
            failure, dict
        ):
            continue
        cause = failure.get("cause")
        if (
            failure.get("operation") == "connect_over_cdp_bounded_reconnect"
            and isinstance(cause, dict)
            and cause.get("type") == "RuntimeError"
            and cause.get("message") == "runtime_error"
            and cause.get("endpoint_unhealthy") is True
        ):
            return True
    return False
