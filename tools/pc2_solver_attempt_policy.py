"""Safe attempt metadata and the boundary between rejection and uncertainty."""

_UNCONFIRMED = frozenset(
    {
        "cancelled",
        "deadline_exceeded",
        "cdp_unavailable",
        "challenge_loading",
        "slider_not_found",
        "slider_endpoint_unconfirmed",
        "execution_unavailable",
    }
)
_FAILURES = _UNCONFIRMED | {
    "manual_required",
    "challenge_retry_exhausted",
    "max_attempts_exceeded",
}


def safe_failure_reason(value: object) -> str | None:
    if isinstance(value, str) and value in _FAILURES:
        return value
    return "other" if value is not None else None


def preserve_unconfirmed_target(value: object) -> bool:
    return isinstance(value, str) and value in _UNCONFIRMED
