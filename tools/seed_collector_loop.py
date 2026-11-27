"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.seed_collector_context import *


def run_seed_collector_loop(
    config: SeedCollectorConfig,
    *,
    repository: PropertyRepository,
    http_session: Any | None = None,
    browserless_seed_probe: Any,
    runtime_context_factory: SeedRuntimeContextFactory | None = None,
    progress_emit_func: SeedProgressEmitFunc | None = None,
) -> dict[str, Any]:
    from tools.detail_worker_statistics import worker_queue_statistics
    from tools.seed_collector_wait import wait_after_seed_run
    from tools.worker_lifecycle import checkpoint, wait

    owns_sessions = runtime_context_factory is None and http_session is None
    if runtime_context_factory is None:
        if http_session is None:
            runtime_context_factory = lambda: _build_runtime_context(config)
        else:
            runtime_context_factory = lambda: http_session
    emit_progress = progress_emit_func or _emit_progress_event
    results: list[dict[str, Any]] = []
    last_runtime_context: Any | None = None

    def _close_session(session_obj: Any) -> None:
        if not owns_sessions or session_obj is None:
            return
        close = getattr(session_obj, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001, S110 -- best-effort session close
                pass
    runs = 0
    pages_attempted = 0
    cycle_summaries: list[dict[str, Any]] = []
    release_worker_leases = getattr(repository, "release_seed_scan_worker_leases", None)
    if callable(release_worker_leases):
        release_summary = release_worker_leases(config.worker_id)
        if int((release_summary or {}).get("released") or 0) > 0:
            release_event = {
                "decision": "seed_scan_worker_leases_released",
                "worker_id": config.worker_id,
                "release_summary": release_summary,
                "counts": repository.seed_queue_counts(),
            }
            emit_progress({"event": "seed_collector_worker_leases_released", **release_event})
            _write_runtime_summary(config.output_dir, release_event)
    initial_counts = repository.seed_queue_counts()
    if _should_ensure_seed_jobs(config, initial_counts):
        _write_runtime_summary(
            config.output_dir,
            {
                "decision": "seed_scan_jobs_ensure_started",
                "worker_id": config.worker_id,
                "job_count": len(_seed_jobs(config)),
                "counts": initial_counts,
            },
        )
        archive_summary = None
        if _should_archive_stale_seed_jobs(config):
            archive_summary = _archive_stale_seed_jobs(config, repository)
            _write_runtime_summary(
                config.output_dir,
                {
                    "decision": "seed_scan_jobs_archive_stale_completed",
                    "worker_id": config.worker_id,
                    "archive_summary": archive_summary,
                    "counts": repository.seed_queue_counts(),
                },
            )
        ensured_jobs = _ensure_seed_scan_jobs(config, repository)
        _write_runtime_summary(
            config.output_dir,
            {
                "decision": "seed_scan_jobs_ensure_completed",
                "worker_id": config.worker_id,
                "ensured_jobs": len(ensured_jobs),
                "ensure_results": ensured_jobs[-20:],
                "archive_summary": archive_summary,
                "counts": repository.seed_queue_counts(),
            },
        )
    else:
        _write_runtime_summary(
            config.output_dir,
            {
                "decision": "seed_scan_jobs_ensure_skipped",
                "reason": "existing_seed_scan_queue",
                "worker_id": config.worker_id,
                "counts": initial_counts,
            },
        )
    try:
        while checkpoint("seed_cycle"):
            runs += 1
            has_work, queue_counts = _has_seed_scan_work(repository)
            if has_work and config.api_base_url:
                pause = _collection_pause_state_with_retry(config.api_base_url)
                if pause.get("operator_paused") or pause.get("reason") == "operator_paused":
                    result = {"decision": "seed_collection_paused", "reason": "operator_paused",
                              "captcha_solver": pause.get("captcha_solver") or {}, "counts": queue_counts}
                    results.append(result)
                    del results[:-20]
                    event = _seed_run_progress_event(runs, [result])
                    cycle_summaries.append(dict(event.get("cycle_summary") or {}))
                    del cycle_summaries[:-20]
                    emit_progress(event)
                    _write_runtime_summary(config.output_dir, event)
                    if config.max_runs is not None and runs >= config.max_runs:
                        break
                    wait_after_seed_run(config, [result], _seed_loop_sleep_seconds(config, [result]))
                    continue
            if not has_work:
                result = {"decision": "seed_scan_queue_empty", "counts": queue_counts}
                _write_runtime_summary(config.output_dir, result)
                results.append(result)
                del results[:-20]
                run_event = _seed_run_progress_event(runs, [result])
                cycle_summaries.append(dict(run_event.get("cycle_summary") or {}))
                del cycle_summaries[:-20]
                emit_progress(run_event)
                _write_runtime_summary(config.output_dir, run_event)
                if config.max_runs is not None and runs >= config.max_runs:
                    break
                sleep_seconds = max(config.loop_interval_seconds, 0)
                emit_progress(
                    {
                        "event": "seed_collector_sleep",
                        "run": runs,
                        "sleep_seconds": sleep_seconds,
                        "counts": run_event.get("counts"),
                    }
                )
                wait(sleep_seconds)
                continue
            try:
                current_http_session = runtime_context_factory()
                if (
                    last_runtime_context is not None
                    and last_runtime_context is not current_http_session
                ):
                    _close_session(last_runtime_context)
                last_runtime_context = current_http_session
            except Exception as exc:  # noqa: BLE001 -- preserve last usable runtime context
                cached_counts = worker_queue_statistics(repository)["counts"]
                if last_runtime_context is not None:
                    current_http_session = last_runtime_context
                    reuse_event = {
                        "event": "seed_collector_runtime_refresh_reused_last_context",
                        "run": runs,
                        "decision": "seed_runtime_refresh_reused_last_context",
                        "error": safe_exception_text(exc),
                        "counts": cached_counts,
                    }
                    emit_progress(reuse_event)
                    _write_runtime_summary(config.output_dir, reuse_event)
                else:
                    failure_event = {
                        "event": "seed_collector_runtime_refresh_failed",
                        "run": runs,
                        "decision": "seed_runtime_refresh_failed",
                        "error": safe_exception_text(exc),
                        "counts": cached_counts,
                    }
                    emit_progress(failure_event)
                    _write_runtime_summary(config.output_dir, failure_event)
                    if config.max_runs is not None and runs >= config.max_runs:
                        break
                    sleep_seconds = max(config.loop_interval_seconds, 0)
                    emit_progress(
                        {
                            "event": "seed_collector_sleep",
                            "run": runs,
                            "sleep_seconds": sleep_seconds,
                            "counts": failure_event.get("counts"),
                        }
                    )
                    wait(sleep_seconds)
                    continue
            run_results: list[dict[str, Any]] = []
            for _page_index in range(max(int(config.pages_per_run or 1), 1)):
                if not checkpoint("seed_page"):
                    break
                result = run_seed_collector_once(
                    config,
                    repository=repository,
                    http_session=current_http_session,
                    browserless_seed_probe=browserless_seed_probe,
                    ensure_jobs=False,
                )
                results.append(result)
                run_results.append(result)
                if _is_page_attempt_result(result):
                    pages_attempted += 1
                partial_run_event = _seed_run_progress_event(runs, run_results)
                partial_run_event["event"] = "seed_collector_run_in_progress"
                _write_runtime_summary(config.output_dir, partial_run_event)
                if result.get("decision") == "seed_scan_queue_empty":
                    break
                if (
                    result.get("decision") == "seed_page_retryable_failure"
                    and result.get("reason") == "list_challenge_page"
                ):
                    break
                if result.get("decision") == "seed_collection_paused":
                    break
                if _page_index + 1 < max(int(config.pages_per_run or 1), 1):
                    delay_seconds = jittered_delay_seconds(
                        config.page_delay_seconds,
                        config.pacing_jitter_ratio,
                    )
                    if delay_seconds > 0:
                        wait(delay_seconds)
            del results[:-20]
            run_event = _seed_run_progress_event(runs, run_results)
            cycle_summaries.append(dict(run_event.get("cycle_summary") or {}))
            del cycle_summaries[:-20]
            emit_progress(run_event)
            _write_runtime_summary(config.output_dir, run_event)
            if config.max_runs is not None and runs >= config.max_runs:
                break
            sleep_seconds = _seed_loop_sleep_seconds(config, run_results)
            emit_progress(
                {
                    "event": "seed_collector_sleep",
                    "run": runs,
                    "sleep_seconds": sleep_seconds,
                    "counts": run_event.get("counts"),
                }
            )
            wait_after_seed_run(config, run_results, sleep_seconds)
    finally:
        _close_session(last_runtime_context)
    summary = {
        "decision": "seed_collector_loop_finished",
        "runs": runs,
        "pages_attempted": pages_attempted,
        "pages_per_run": max(int(config.pages_per_run or 1), 1),
        "last_decision": results[-1].get("decision") if results else None,
        "last_cycle_summary": cycle_summaries[-1] if cycle_summaries else {},
        "cycle_summaries": cycle_summaries[-20:],
        "results": results[-20:],
        "counts": repository.seed_queue_counts(),
    }
    _write_runtime_summary(config.output_dir, summary)
    return summary


__all__ = (
    'run_seed_collector_loop',
)
