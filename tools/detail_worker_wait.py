"""Bounded recovery checks without bypassing challenge or operator backoff."""

import math
import time

from tools import worker_lifecycle
from tools.cdp_reconnect_health import batch_has_cdp_outage, cdp_metadata_recovered
from tools.detail_worker_context import DetailWorkerConfig
from tools.detail_worker_pause_state import (
    collection_scope_statuses,
    operator_pause_requested,
)
from tools.internal_api_http import fetch_json


def _receipt(started, seconds, polls, exit_reason, report_floor=0, cdp_polls=0):
    return {
        "requested_wait_seconds": seconds,
        "actual_wait_seconds": round(max(0.0, time.monotonic() - started), 3),
        "status_poll_count": polls,
        "wait_exit": exit_reason,
        **({"cdp_poll_count": cdp_polls} if cdp_polls else {}),
        **({"report_backoff_seconds": report_floor} if report_floor else {}),
    }


def wait_without_auth_poll(seconds):
    started = time.monotonic()
    worker_lifecycle.wait(seconds)
    return _receipt(started, seconds, 0, "wait_returned")


def _suppressed_report_retry_floor(result):
    floor = 0
    for item in result.get("results") or []:
        if (
            not isinstance(item, dict)
            or item.get("reason") != "detail_stale_challenge_ignored"
        ):
            continue
        report = item.get("captcha_solver_report")
        if (
            not isinstance(report, dict)
            or report.get("status")
            not in (
                "recent_auth_complete",
                "recent_force_reset",
            )
            or report.get("scope") not in (None, "", "detail")
        ):
            continue
        raw = report.get("retry_after_seconds")
        if isinstance(raw, bool):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(value) and value > 0:
            floor = max(floor, math.ceil(value))
    return floor


def wait_after_detail_batch(
    config: DetailWorkerConfig, result: dict, seconds: float
) -> dict:
    started, polls, cdp_polls = time.monotonic(), 0, 0
    challenge_wait = any(
        isinstance(item, dict)
        and (
            item.get("decision") == "detail_collection_paused"
            or item.get("reason")
            in {"detail_challenge_page", "detail_stale_challenge_ignored"}
        )
        for item in result.get("results") or []
    )
    endpoint = str(getattr(config, "cdp_endpoint", "") or "")
    cdp_wait = (
        not challenge_wait
        and endpoint.startswith(("http://", "https://"))
        and batch_has_cdp_outage(result)
    )
    if (
        config.analysis_only
        or not config.api_base_url
        or not (challenge_wait or cdp_wait)
    ):
        worker_lifecycle.wait(seconds)
        return _receipt(started, seconds, polls, "wait_returned")

    report_floor = _suppressed_report_retry_floor(result)
    effective_seconds = max(seconds, report_floor)
    if effective_seconds <= 30:
        worker_lifecycle.wait(effective_seconds)
        return _receipt(started, seconds, polls, "wait_returned", report_floor)
    deadline = started + effective_seconds
    earliest_wake = started + report_floor
    while worker_lifecycle.checkpoint("detail_auth_backoff"):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _receipt(
                started, seconds, polls, "deadline_elapsed", report_floor, cdp_polls
            )
        until_floor = earliest_wake - time.monotonic()
        worker_lifecycle.wait(
            min(remaining, 30, until_floor) if until_floor > 0 else min(remaining, 30)
        )
        if not worker_lifecycle.checkpoint("detail_auth_backoff"):
            return _receipt(
                started, seconds, polls, "stopping", report_floor, cdp_polls
            )
        # Suppression can leave the scope clear throughout; that is not new recovery.
        if time.monotonic() < earliest_wake:
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            continue
        try:
            polls += 1
            status = fetch_json(
                config.api_base_url.rstrip("/") + "/status",
                timeout=min(5, remaining),
            )
        except (OSError, ValueError, TimeoutError):
            continue
        if not worker_lifecycle.checkpoint("detail_auth_backoff"):
            break
        if time.monotonic() >= deadline:
            continue
        if not isinstance(status, dict):
            continue
        if operator_pause_requested(status):
            continue
        scopes = collection_scope_statuses(status)
        detail = scopes.get("detail") if isinstance(scopes, dict) else None
        seed = scopes.get("seed") if isinstance(scopes, dict) else None
        # The aggregate pause includes seed-only challenges. A confirmed clear
        # detail scope must not inherit another stage's 15-minute backoff.
        if status.get("paused") is not False and not (
            status.get("paused") is True
            and isinstance(seed, dict)
            and seed.get("paused") is True
        ):
            continue
        if (
            isinstance(detail, dict)
            and detail.get("paused") is False
            and detail.get("manual_required") is False
            and not detail.get("challenge_id")
        ):
            if cdp_wait:
                if not worker_lifecycle.checkpoint("detail_auth_backoff"):
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    continue
                cdp_polls += 1
                if not cdp_metadata_recovered(
                    endpoint, timeout_seconds=min(5, remaining)
                ):
                    continue
                if not worker_lifecycle.checkpoint("detail_auth_backoff"):
                    return _receipt(
                        started, seconds, polls, "stopping", report_floor, cdp_polls
                    )
                if time.monotonic() >= deadline:
                    continue
            return _receipt(
                started,
                seconds,
                polls,
                "cdp_resumed"
                if cdp_wait
                else "report_backoff_elapsed"
                if report_floor
                else "detail_resumed",
                report_floor,
                cdp_polls,
            )
    return _receipt(started, seconds, polls, "stopping", report_floor, cdp_polls)
