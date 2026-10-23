"""Classify backend-wide transport failures without exposing provider payloads."""

import json

import requests

_QUOTA_MARKERS = (
    "insufficient_user_quota",
    "insufficient_quota",
    "insufficient balance",
    "credit insufficient",
)


def is_backend_http_failure(error: BaseException) -> bool:
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True
    if not isinstance(error, requests.HTTPError):
        return False
    response = error.response
    status = getattr(response, "status_code", None)
    if type(status) is not int:
        return False
    if status in {401, 403, 404, 408, 425, 429} or 500 <= status <= 599:
        return True
    if status != 400:
        return False
    raw = getattr(response, "content", b"")
    if not isinstance(raw, bytes) or len(raw) > 8192:
        return False
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError):
        return False
    details = body.get("error") if isinstance(body, dict) else None
    if not isinstance(details, dict):
        return False
    # Only account-quota codes/messages distinguish a global 400 from bad item input.
    fields = [details.get(name) for name in ("code", "type", "message")]
    return any(
        marker in value.casefold()
        for value in fields
        if isinstance(value, str)
        for marker in _QUOTA_MARKERS
    )
