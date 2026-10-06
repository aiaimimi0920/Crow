"""Ready, requested-target proof for live solver success; no HTTP or browser I/O."""

from .collection.adapters.taobao_auth_target import (
    canonical_auth_target,
    same_auth_target,
    seed_payload_is_authenticated,
)
from .collection.adapters.taobao_detail_auth import detail_payload_authenticated
from .collection.adapters.taobao_list_probe import (
    extract_list_payload,
    summarize_list_page,
)


def _bound_target(href, target_url):
    for scope in ("detail", "seed"):
        try:
            requested = canonical_auth_target(scope, target_url)
            current = canonical_auth_target(scope, href)
        except (ValueError, TypeError, AttributeError):
            continue
        if same_auth_target(scope, current, requested):
            return scope, requested
    return None


def ready_target_matches(evidence, target_url):
    """A challenge route may confirm explicit success, but never another target."""
    return (
        evidence.get("readyState") in {"interactive", "complete"}
        and _bound_target(evidence.get("href"), target_url) is not None
    )


def _payload_authenticated(html, summary, target_url):
    if not html or summary.get("readyState") not in {"interactive", "complete"}:
        return False
    if any(
        summary.get(key)
        for key in (
            "hasSlider",
            "hasChallengeWidget",
            "explicitFailure",
            "loginRequired",
            "frameChallengePresent",
        )
    ):
        return False
    bound = _bound_target(summary.get("href"), target_url)
    if bound is None:
        return False
    scope, requested = bound
    href = summary["href"]
    try:
        if scope == "detail":
            return detail_payload_authenticated(html, href, requested)
        payload = extract_list_payload(html)
        health = summarize_list_page(html, final_url=href)
        return seed_payload_is_authenticated(
            payload, health, final_url=href, target_url=requested
        )
    except (ValueError, TypeError, AttributeError):
        # Incomplete or malformed data is unconfirmed, never teardown success.
        return False


def finalize_page_summary(value, target_url):
    """Consume private HTML before any caller can log, retain or refresh it."""
    summary = dict(value)
    html = summary.pop("_verificationHtml", "")
    authenticated = _payload_authenticated(html, summary, target_url)
    summary["validAuctionPayload"] = authenticated
    summary["challengePresent"] = bool(
        summary.get("hasSlider")
        or summary.get("hasChallengeWidget")
        or summary.get("explicitFailure")
        or summary.get("frameChallengePresent")
        or (
            (summary.get("hardBlock") or summary.get("challengeMarker"))
            and not authenticated
        )
    )
    summary["authenticatedPage"] = authenticated and not summary["challengePresent"]
    return summary
