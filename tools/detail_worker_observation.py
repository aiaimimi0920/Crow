"""Bounded worker telemetry; never infer network requests from item attempts."""

from collections import Counter
import math

ITEM_COUNTERS = (
    "claimed_items",
    "process_item_calls",
    "analysis_item_calls",
    "paused_results",
)
DECISIONS = frozenset(
    {
        "detail_queue_empty",
        "detail_analysis_queue_empty",
        "detail_collection_paused",
        "detail_item_completed",
        "detail_item_raw_captured",
        "detail_item_retryable_failure",
        "detail_analysis_completed",
        "detail_analysis_backend_unavailable",
        "detail_analysis_retryable_failure",
    }
)
REASONS = frozenset(
    {
        "collection_paused",
        "operator_paused",
        "manual_required",
        "captcha_solver_manual_required",
        "captcha_solver_running",
        "collection_paused_flag",
        "detail_stale_challenge_ignored",
        "detail_challenge_page",
        "transient_dns_error",
        "detail_cdp_unreachable",
        "exception",
    }
)


def item_observation():
    return dict.fromkeys(ITEM_COUNTERS, 0)


def safe_category(value, allowed):
    return value if isinstance(value, str) and value in allowed else "other"


def batch_observation(results, *, elapsed_seconds):
    totals = item_observation()
    decisions, reasons = Counter(), Counter()
    missing = 0
    for result in results:
        result = result if isinstance(result, dict) else {}
        if any(
            type(result.get(key)) is not int or result[key] not in (0, 1)
            for key in ITEM_COUNTERS
        ):
            missing += 1
        for key in ITEM_COUNTERS:
            value = result.get(key)
            # Each result represents at most one item; malformed/old inputs are unknown.
            if type(value) is int and value in (0, 1):
                totals[key] += value
        decisions[safe_category(result.get("decision"), DECISIONS)] += 1
        if "reason" in result:
            reasons[safe_category(result["reason"], REASONS)] += 1
    elapsed = (
        round(max(0.0, elapsed_seconds), 3)
        if type(elapsed_seconds) in (int, float) and math.isfinite(elapsed_seconds)
        else None
    )
    return {
        **totals,
        "item_observation_missing": missing,
        "decision_counts": dict(decisions),
        "reason_counts": dict(reasons),
        "page_requests": None,
        "page_requests_observed": False,
        "batch_elapsed_seconds": elapsed,
    }
