"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.seed_collector_context import *


def _build_runtime_context(config: SeedCollectorConfig) -> Any:
    cookies = export_cookies(config.cdp_endpoint)
    return build_http(cookies)


def _emit_progress_event(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def _summary_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _seed_cycle_summary(run_results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    decision_counts: dict[str, int] = {}
    for result in run_results:
        decision = str(result.get("decision") or "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    collected = [result for result in run_results if result.get("decision") == "seed_page_collected"]
    retryable_failures = [result for result in run_results if result.get("decision") == "seed_page_retryable_failure"]
    upserts = [result.get("upsert") for result in collected if isinstance(result.get("upsert"), dict)]
    return {
        "pages_attempted": sum(1 for result in run_results if _is_page_attempt_result(result)),
        "pages_collected": len(collected),
        "retryable_failures": len(retryable_failures),
        "paused_count": decision_counts.get("seed_collection_paused", 0),
        "queue_empty_count": decision_counts.get("seed_scan_queue_empty", 0),
        "items_seen": sum(_summary_int(upsert.get("seen")) for upsert in upserts),
        "items_collected": sum(_summary_int(result.get("item_count")) for result in collected),
        "new_items": sum(_summary_int(upsert.get("new_items")) for upsert in upserts),
        "existing_items": sum(_summary_int(upsert.get("existing_items")) for upsert in upserts),
        "new_occurrences": sum(_summary_int(upsert.get("new_occurrences")) for upsert in upserts),
        "decision_counts": decision_counts,
    }


def _seed_run_progress_event(run: int, run_results: list[dict[str, Any]]) -> dict[str, Any]:
    last_result = run_results[-1] if run_results else {}
    cycle_summary = _seed_cycle_summary(run_results)
    last_auth_probe = next(
        (
            result.get("auth_probe")
            for result in reversed(run_results)
            if isinstance(result.get("auth_probe"), dict)
        ),
        None,
    )
    event = {
        "event": "seed_collector_run",
        "run": run,
        "pages_attempted": cycle_summary["pages_attempted"],
        "pages_collected": cycle_summary["pages_collected"],
        "retryable_failures": cycle_summary["retryable_failures"],
        "new_occurrences": cycle_summary["new_occurrences"],
        "last_decision": last_result.get("decision"),
        "last_reason": last_result.get("reason"),
        "last_item_count": last_result.get("item_count"),
        "counts": last_result.get("counts"),
        "cycle_summary": cycle_summary,
    }
    if last_auth_probe is not None:
        event["last_auth_probe"] = last_auth_probe
        event["auth_probe_attempted"] = bool(last_auth_probe.get("attempted"))
    return event


def _is_page_attempt_result(result: dict[str, Any]) -> bool:
    return result.get("decision") not in {"seed_scan_queue_empty", "seed_collection_paused"}


def _seed_run_collected_page(run_results: Sequence[dict[str, Any]]) -> bool:
    return any(result.get("decision") == "seed_page_collected" for result in run_results)


def _seed_run_attempted_auth_probe(run_results: Sequence[dict[str, Any]]) -> bool:
    for result in run_results:
        auth_probe = result.get("auth_probe")
        if isinstance(auth_probe, dict) and auth_probe.get("attempted"):
            return True
    return False


def _seed_run_hit_challenge_page(run_results: Sequence[dict[str, Any]]) -> bool:
    return any(
        result.get("decision") == "seed_page_retryable_failure"
        and result.get("reason") == "list_challenge_page"
        for result in run_results
    )


def _seed_loop_sleep_seconds(config: SeedCollectorConfig, run_results: Sequence[dict[str, Any]]) -> int:
    if _seed_run_collected_page(run_results):
        interval = config.active_loop_interval_seconds
        if interval is None:
            interval = config.loop_interval_seconds
        return max(int(interval), 0)
    if _seed_run_attempted_auth_probe(run_results) or _seed_run_hit_challenge_page(run_results):
        return max(int(config.auth_probe_interval_seconds), 0)
    return max(config.loop_interval_seconds, 0)


def _summary_optional_non_negative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _seed_page_has_next(
    *,
    task_page: Any,
    task_max_page: Any,
    list_summary: dict[str, Any],
    filtered_items: Sequence[dict[str, Any]],
) -> bool:
    try:
        current_page = int(task_page)
    except (TypeError, ValueError):
        current_page = 1
    try:
        max_page = int(task_max_page)
    except (TypeError, ValueError):
        max_page = current_page
    if current_page >= max_page:
        return False
    raw_item_count = _summary_optional_non_negative_int(list_summary.get("item_count"))
    if raw_item_count is not None:
        return raw_item_count > 0
    return bool(filtered_items)


def _report_manual_seed_challenge(config: SeedCollectorConfig, target_url: str) -> dict[str, Any] | None:
    if (
        not config.manual_challenge_reporting
        or config.solver_enabled
        or not str(config.api_base_url or "").strip()
    ):
        return None

    from tools.taobao_login_health import report_captcha_via_api

    try:
        return dict(
            report_captcha_via_api(
                config.api_base_url,
                config.cdp_endpoint,
                _normalize_seed_challenge_target_url(target_url, allow_default=True),
                manual_only=True,
            )
        )
    except Exception as exc:
        return {"status": "report_failed", "error": safe_exception_text(exc)}


__all__ = (
    '_build_runtime_context',
    '_emit_progress_event',
    '_summary_int',
    '_seed_cycle_summary',
    '_seed_run_progress_event',
    '_is_page_attempt_result',
    '_seed_run_collected_page',
    '_seed_run_attempted_auth_probe',
    '_seed_run_hit_challenge_page',
    '_seed_loop_sleep_seconds',
    '_summary_optional_non_negative_int',
    '_seed_page_has_next',
    '_report_manual_seed_challenge',
)
