"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.detail_worker_context import *


def run_detail_worker_batch(
    config: DetailWorkerConfig,
    *,
    repository: PropertyRepository,
    http_session: Any,
    browser_pages: dict[str, tuple[str, str]],
    process_item_func: Callable[..., dict[str, Any]] = process_item,
    analyze_item_func: AnalyzeItemFunc = analyze_raw_item,
) -> dict[str, Any]:
    from tools.detail_worker_observation import batch_observation
    from tools.detail_worker_statistics import worker_queue_statistics
    from tools.worker_lifecycle import checkpoint, wait

    started = time.monotonic()
    if config.llm_preflight_enabled and not config.raw_only:
        preflight = _run_llm_preflight(config)
    else:
        preflight = None
    if _llm_preflight_is_unavailable(preflight) or (
        preflight and preflight.get("error")
    ):
        summary = {
            "decision": "detail_worker_llm_unavailable",
            "attempts": 0,
            "completed": 0,
            "target_success": config.target_success,
            "max_attempts": config.max_attempts,
            "llm_preflight": preflight,
            "results": [],
            **worker_queue_statistics(repository),
            **batch_observation([], elapsed_seconds=time.monotonic() - started),
        }
        _write_runtime_summary(config.output_dir, summary)
        return summary
    results: list[dict[str, Any]] = []
    attempted_item_ids: set[str] = set()
    completed = 0
    attempts = 0
    challenge_break = False
    challenge_retry_after_seconds = 0
    while (
        attempts < config.max_attempts
        and completed < config.target_success
        and checkpoint("detail_item")
    ):
        attempts += 1
        if config.analysis_only:
            result = run_detail_analysis_once(
                config,
                repository=repository,
                analyze_item_func=analyze_item_func,
                exclude_item_ids=attempted_item_ids,
            )
        else:
            result = run_detail_worker_once(
                config,
                repository=repository,
                http_session=http_session,
                browser_pages=browser_pages,
                process_item_func=process_item_func,
                exclude_item_ids=attempted_item_ids,
            )
        results.append(result)
        item_id = result.get("item_id")
        if item_id:
            attempted_item_ids.add(str(item_id))
        if result.get("decision") in {
            "detail_queue_empty",
            "detail_analysis_queue_empty",
            "detail_collection_paused",
        }:
            # Hand control back to the existing scope-aware, cancellable batch wait.
            break
        item_completed = result.get("decision") in {
            "detail_item_completed",
            "detail_item_raw_captured",
            "detail_analysis_completed",
        }
        if item_completed:
            completed += 1
        if result.get("decision") == "detail_analysis_backend_unavailable":
            break
        challenge_break = _detail_challenge_should_break_batch(config, result)
        challenge_retry_after_seconds = _detail_challenge_retry_after_seconds(
            config, result
        )
        if challenge_break:
            break
        if attempts < config.max_attempts and completed < config.target_success:
            delay_seconds = _detail_inter_item_delay_seconds(
                config, item_completed=item_completed
            )
            if delay_seconds > 0:
                wait(delay_seconds)
    summary = {
        "decision": "detail_worker_batch_finished",
        "attempts": attempts,
        "completed": completed,
        "target_success": config.target_success,
        "max_attempts": config.max_attempts,
        "llm_preflight": preflight,
        "challenge_break": challenge_break,
        "retry_after_seconds": challenge_retry_after_seconds,
        "results": results,
        **worker_queue_statistics(repository),
        **batch_observation(results, elapsed_seconds=time.monotonic() - started),
    }
    _write_runtime_summary(config.output_dir, summary)
    return summary


def _detail_inter_item_delay_seconds(
    config: DetailWorkerConfig, *, item_completed: bool
) -> float:
    if config.analysis_only:
        return 0.0
    base_delay = (
        config.success_delay_seconds if item_completed else config.failure_delay_seconds
    )
    return jittered_delay_seconds(base_delay, config.pacing_jitter_ratio)


def _detail_batch_sleep_seconds(
    config: DetailWorkerConfig, result: dict[str, Any]
) -> int:
    completed = result.get("completed")
    try:
        completed_count = int(completed)
    except (TypeError, ValueError):
        completed_count = 0
    if completed_count > 0:
        interval = config.active_loop_interval_seconds
        if interval is None:
            interval = config.loop_interval_seconds
        base_sleep = max(int(interval), 0)
    else:
        base_sleep = max(config.loop_interval_seconds, 0)

    challenge_retry_after = 0
    for item_result in result.get("results") or []:
        if not isinstance(item_result, dict):
            continue
        challenge_retry_after = max(
            challenge_retry_after,
            _detail_challenge_retry_after_seconds(config, item_result),
        )
    return max(base_sleep, challenge_retry_after)


def run_detail_worker_loop(
    config: DetailWorkerConfig,
    *,
    repository: PropertyRepository,
    http_session: Any | None = None,
    browser_pages: dict[str, tuple[str, str]] | None = None,
    runtime_context_factory: RuntimeContextFactory | None = None,
    progress_emit_func: ProgressEmitFunc | None = None,
) -> dict[str, Any]:
    from contextlib import nullcontext

    from tools.detail_worker_sessions import OwnedRuntimeContext

    if runtime_context_factory is not None:
        context_scope = nullcontext(runtime_context_factory)
    elif http_session is not None and browser_pages is not None:
        context_scope = nullcontext(lambda: (http_session, browser_pages))
    else:
        context_scope = OwnedRuntimeContext(lambda: _build_runtime_context(config))
    with context_scope as factory:
        return _run_detail_worker_loop(
            config,
            repository=repository,
            runtime_context_factory=factory,
            progress_emit_func=progress_emit_func,
        )


def _run_detail_worker_loop(
    config: DetailWorkerConfig,
    *,
    repository: PropertyRepository,
    runtime_context_factory: RuntimeContextFactory,
    progress_emit_func: ProgressEmitFunc | None = None,
) -> dict[str, Any]:
    from tools.detail_worker_statistics import worker_queue_statistics
    from tools.detail_worker_wait import wait_after_detail_batch, wait_without_auth_poll
    from tools.worker_lifecycle import checkpoint

    emit_progress = progress_emit_func or _emit_progress_event
    results: list[dict[str, Any]] = []
    last_runtime_context: RuntimeContext | None = None
    runs = 0
    release_worker_leases = getattr(
        repository, "release_seed_detail_worker_leases", None
    )
    if callable(release_worker_leases):
        release_summary = release_worker_leases(config.worker_id)
        if int((release_summary or {}).get("released") or 0) > 0:
            release_event = {
                "decision": "detail_worker_leases_released",
                "worker_id": config.worker_id,
                "release_summary": release_summary,
                **worker_queue_statistics(repository),
            }
            emit_progress({"event": "detail_worker_leases_released", **release_event})
            _write_runtime_summary(config.output_dir, release_event)
    while checkpoint("detail_cycle"):
        runs += 1
        try:
            current_http_session, current_browser_pages = runtime_context_factory()
            last_runtime_context = (current_http_session, current_browser_pages)
        except Exception as exc:  # noqa: BLE001 - preserve the last usable context after a refresh failure.
            if last_runtime_context is not None:
                current_http_session, current_browser_pages = last_runtime_context
                reuse_event = {
                    "event": "detail_worker_runtime_refresh_reused_last_context",
                    "run": runs,
                    "decision": "detail_runtime_refresh_reused_last_context",
                    "error": safe_exception_text(exc),
                    **worker_queue_statistics(repository),
                }
                emit_progress(reuse_event)
                _write_runtime_summary(config.output_dir, reuse_event)
            else:
                failure_event = {
                    "event": "detail_worker_runtime_refresh_failed",
                    "run": runs,
                    "decision": "detail_runtime_refresh_failed",
                    "error": safe_exception_text(exc),
                    **worker_queue_statistics(repository),
                }
                emit_progress(failure_event)
                _write_runtime_summary(config.output_dir, failure_event)
                if config.max_runs is not None and runs >= config.max_runs:
                    break
                sleep_seconds = max(config.loop_interval_seconds, 0)
                emit_progress(
                    {
                        "event": "detail_worker_sleep",
                        "run": runs,
                        "sleep_seconds": sleep_seconds,
                        "counts": failure_event.get("counts"),
                        "counts_metadata": failure_event.get("counts_metadata"),
                    }
                )
                receipt = wait_without_auth_poll(sleep_seconds)
                emit_progress(
                    {"event": "detail_worker_wait_finished", "run": runs, **receipt}
                )
                continue
        result = run_detail_worker_batch(
            config,
            repository=repository,
            http_session=current_http_session,
            browser_pages=current_browser_pages,
        )
        results.append(result)
        # Bound live retention as well as the final summary of an unattended loop.
        del results[:-20]
        emit_progress(_detail_batch_progress_event(runs, result))
        if config.max_runs is not None and runs >= config.max_runs:
            break
        sleep_seconds = _detail_batch_sleep_seconds(config, result)
        emit_progress(
            {
                "event": "detail_worker_sleep",
                "run": runs,
                "sleep_seconds": sleep_seconds,
                "counts": result.get("counts"),
                **(
                    {"counts_metadata": result["counts_metadata"]}
                    if "counts_metadata" in result
                    else {}
                ),
            }
        )
        receipt = wait_after_detail_batch(config, result, sleep_seconds)
        emit_progress({"event": "detail_worker_wait_finished", "run": runs, **receipt})
    summary = {
        "decision": "detail_worker_loop_finished",
        "runs": runs,
        "last_decision": results[-1].get("decision") if results else None,
        "results": results[-20:],
        **worker_queue_statistics(repository),
    }
    _write_runtime_summary(config.output_dir, summary)
    return summary


__all__ = (
    "_detail_batch_sleep_seconds",
    "_detail_inter_item_delay_seconds",
    "_run_detail_worker_loop",
    "run_detail_worker_batch",
    "run_detail_worker_loop",
)
