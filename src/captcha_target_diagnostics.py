"""Safe identity differences from snapshots; never authorize input or success."""

from urllib.parse import parse_qsl, urlsplit

from .captcha_navigation_receipt import safe_navigation_fields
from .captcha_verification import ready_target_matches
from .collection.adapters.taobao_auth_target import (
    SEED_IDENTITY_QUERY_KEYS,
    canonical_auth_target,
)


def _canonical(value):
    if not isinstance(value, str):
        return None, None
    for scope in ("seed", "detail"):
        try:
            return scope, urlsplit(canonical_auth_target(scope, value))
        except (ValueError, TypeError, AttributeError):
            continue
    return None, None


def target_binding_fields(summary, target_url):
    """Compare canonical identities, emitting only fixed enums, never values."""
    expected_scope, expected = _canonical(target_url)
    scope, current = _canonical(summary.get("href"))
    fields = {key: "not_compared" for key in sorted(SEED_IDENTITY_QUERY_KEYS)}
    if expected is None:
        return {"binding": "request_invalid", **fields}
    if current is None:
        return {"binding": "current_invalid", **fields}
    if scope != expected_scope:
        return {"binding": "scope_changed", **fields}
    if (expected.hostname, expected.path) != (current.hostname, current.path):
        return {"binding": "path_changed", **fields}
    before, after = parse_qsl(expected.query), parse_qsl(current.query)
    for key in fields:
        requested = sorted(value for name, value in before if name == key)
        observed = sorted(value for name, value in after if name == key)
        fields[key] = (
            "both_absent"
            if not requested and not observed
            else "current_missing"
            if not observed
            else "request_missing"
            if not requested
            else "equal"
            if requested == observed
            else "different"
        )
    matches = all(value in {"equal", "both_absent"} for value in fields.values())
    return {"binding": "match" if matches else "query_changed", **fields}


def log_target_binding(logger, stage, summary, target_url, *, navigation=None):
    """Log fixed enums only; diagnostic comparisons never change binding policy."""
    fields = target_binding_fields(summary, target_url)
    suffix = ""
    if navigation:
        suffix = " " + " ".join(
            f"{key}={value}"
            for key, value in safe_navigation_fields(navigation).items()
        )
    logger.info(
        "[SOLVER] Target binding: stage=%s binding=%s "
        "location_code=%s st_param=%s auction_start_seg=%s page=%s%s",
        stage,
        fields["binding"],
        fields["location_code"],
        fields["st_param"],
        fields["auction_start_seg"],
        fields["page"],
        suffix,
    )


def _diagnostic_flag(summary, key):
    value = summary.get(key)
    return value if type(value) is bool else None


def log_missing_slider(logger, summary, target_url):
    """Keep the existing missing-slider fields bounded and free of page content."""
    ready = summary.get("readyState")
    logger.info(
        "[SOLVER] Slider unavailable: ready=%s probeFailed=%s "
        "targetReady=%s challengePresent=%s loginRequired=%s "
        "hardBlock=%s explicitFailure=%s authenticatedPage=%s",
        ready if ready in ("loading", "interactive", "complete") else "unknown",
        _diagnostic_flag(summary, "probeFailed"),
        ready_target_matches(summary, target_url),
        _diagnostic_flag(summary, "challengePresent"),
        _diagnostic_flag(summary, "loginRequired"),
        _diagnostic_flag(summary, "hardBlock"),
        _diagnostic_flag(summary, "explicitFailure"),
        _diagnostic_flag(summary, "authenticatedPage"),
    )
