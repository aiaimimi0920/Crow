"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.detail_worker_context import *


def run_detail_worker_once(
    config: DetailWorkerConfig,
    *,
    repository: PropertyRepository,
    http_session: Any,
    browser_pages: dict[str, tuple[str, str]],
    process_item_func: Callable[..., dict[str, Any]] = process_item,
    exclude_item_ids: set[str] | None = None,
) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pause_state = _collection_pause_state_with_retry(config.api_base_url)
    pause_override = False
    if pause_state.get("paused"):
        if _pause_state_has_resolved_open_detail_page(pause_state, browser_pages):
            pause_override = True
        else:
            summary = {
                "decision": "detail_collection_paused",
                "reason": pause_state.get("reason") or "collection_paused",
                "captcha_solver": pause_state.get("captcha_solver") or {},
                "counts": repository.seed_queue_counts(),
            }
            _write_runtime_summary(config.output_dir, summary)
            return summary

    seed = repository.claim_seed_detail_item(
        config.worker_id,
        lease_seconds=config.lease_seconds,
        exclude_item_ids=exclude_item_ids,
        max_item_attempts=config.item_max_attempts,
        failure_cooldown_seconds=config.failure_cooldown_seconds,
    )
    if seed is None:
        summary = {"decision": "detail_queue_empty"}
        _write_runtime_summary(config.output_dir, summary)
        return summary

    item_id = str(seed.get("item_id") or seed.get("id") or seed.get("source_item_id"))
    detail_target_url = ""
    try:
        detail_target_url = _detail_seed_target_url(
            seed,
            item_id,
            adapter=config.collection_adapter,
        )
        selected = process_item_func(
            http_session,
            seed,
            browser_pages,
            config=_live_config(config, target_url=detail_target_url),
        )
        final_json_path = config.output_dir / item_id / "final.json"
        selected_json_path = config.output_dir / item_id / "selected.json"
        if config.raw_only:
            detail_html_path = config.output_dir / item_id / "detail.html"
            description_json_path = config.output_dir / item_id / "description-data.json"
            _assert_raw_detail_artifact_is_not_challenge(
                detail_html_path=detail_html_path,
                selected_json_path=selected_json_path,
            )
            repository.mark_seed_raw_detail_captured(
                item_id,
                detail_html_path=str(detail_html_path),
                description_json_path=str(description_json_path),
                selected_json_path=str(selected_json_path),
            )
            archived_path = _archive_raw_detail_if_configured(
                config=config,
                detail_html_path=detail_html_path,
                item_id=item_id,
            )
            summary = {
                "decision": "detail_item_raw_captured",
                "item_id": item_id,
                "selected": selected,
                "detail_html_path": str(detail_html_path),
                "description_json_path": str(description_json_path),
                "selected_json_path": str(selected_json_path),
                "counts": repository.seed_queue_counts(),
            }
            if archived_path:
                summary["detail_archive_path"] = archived_path
            if pause_override:
                summary["pause_override"] = "resolved_open_detail_page"
            _write_runtime_summary(config.output_dir, summary)
            return summary
        final_item = _load_final_item(config.output_dir, item_id)
        if final_item is not None:
            repository.upsert_flat_item(
                final_item,
                event_type="detail_worker_completed",
                event_payload={
                    "source": "detail_worker",
                    "item_id": item_id,
                    "seed_url": seed.get("url"),
                    "source_page_url": seed.get("source_page_url"),
                    "final_json_path": str(final_json_path),
                    "selected_json_path": str(selected_json_path),
                },
            )
        repository.mark_seed_detail_completed(
            item_id,
            final_json_path=str(final_json_path),
            selected_json_path=str(selected_json_path),
        )
        summary = {
            "decision": "detail_item_completed",
            "item_id": item_id,
            "selected": selected,
            "final_json_path": str(final_json_path),
            "selected_json_path": str(selected_json_path),
            "counts": repository.seed_queue_counts(),
        }
        if pause_override:
            summary["pause_override"] = "resolved_open_detail_page"
        _write_runtime_summary(config.output_dir, summary)
        return summary
    except Exception as exc:
        is_challenge_error = _is_detail_challenge_error(exc)
        is_transient_dns = _is_transient_dns_error(exc)
        is_cdp_unreachable = isinstance(exc, CdpEndpointUnavailableError)
        preserve_retry_budget = _challenge_retry_budget_preserved(
            is_challenge_error=is_challenge_error,
            is_transient_dns=is_transient_dns,
        ) or is_cdp_unreachable
        captcha_solver_report: dict[str, Any] | None = None
        if (
            is_challenge_error
            and (config.solver_enabled or config.manual_challenge_reporting)
            and str(config.api_base_url or "").strip()
        ):
            try:
                report_args = (
                    config.api_base_url,
                    config.cdp_endpoint,
                    detail_target_url,
                )
                if config.solver_enabled:
                    captcha_solver_report = _report_captcha_solver(*report_args)
                else:
                    captcha_solver_report = _report_captcha_solver(*report_args, manual_only=True)
            except Exception as solver_exc:
                captcha_solver_report = {"status": "report_failed", "error": safe_exception_text(solver_exc)}
        repository.mark_seed_detail_failed(
            item_id,
            safe_exception_text(exc),
            retryable=True,
            revert_attempt=preserve_retry_budget,
            restore_pending=preserve_retry_budget,
        )
        stale_challenge_suppressed = bool(
            is_challenge_error and _captcha_report_suppresses_challenge(captcha_solver_report)
        )
        summary = {
            "decision": "detail_item_retryable_failure",
            "reason": (
                "detail_stale_challenge_ignored"
                if stale_challenge_suppressed
                else "detail_challenge_page"
                if is_challenge_error
                else "transient_dns_error"
                if is_transient_dns
                else "detail_cdp_unreachable"
                if is_cdp_unreachable
                else "exception"
            ),
            "item_id": item_id,
            "error": safe_exception_text(exc),
            "traceback": safe_exception_traceback(exc),
            "counts": repository.seed_queue_counts(),
        }
        if pause_override:
            summary["pause_override"] = "resolved_open_detail_page"
        if preserve_retry_budget:
            summary["retry_budget_preserved"] = True
        if is_cdp_unreachable:
            summary["cdp_health"] = _build_cdp_unreachable_health(
                config,
                detail_target_url,
            )
        if captcha_solver_report is not None:
            summary["captcha_solver_report"] = captcha_solver_report
        if stale_challenge_suppressed:
            summary["challenge_suppressed"] = True
        _write_runtime_summary(config.output_dir, summary)
        return summary


def run_detail_analysis_once(
    config: DetailWorkerConfig,
    *,
    repository: PropertyRepository,
    analyze_item_func: AnalyzeItemFunc = analyze_raw_item,
    exclude_item_ids: set[str] | None = None,
) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    seed = repository.claim_seed_raw_detail_item(
        config.worker_id,
        lease_seconds=config.lease_seconds,
        exclude_item_ids=exclude_item_ids,
        max_analysis_attempts=config.item_max_attempts,
    )
    if seed is None:
        summary = {"decision": "detail_analysis_queue_empty"}
        _write_runtime_summary(config.output_dir, summary)
        return summary

    item_id = str(seed.get("item_id") or seed.get("id") or seed.get("source_item_id"))
    try:
        staged_artifacts = _stage_raw_detail_artifacts_for_analysis(seed, output_dir=config.output_dir, item_id=item_id)
        selected = analyze_item_func(item_id, output_dir=config.output_dir, do_risk=config.do_risk)
        module_b_receipt = selected.get("analysis_module_b") if isinstance(selected, dict) else None
        _record_analysis_module_b_receipt(repository, item_id=item_id, receipt=module_b_receipt)
        final_json_path = config.output_dir / item_id / "final.json"
        selected_json_path = config.output_dir / item_id / "selected.json"
        final_item = _load_final_item(config.output_dir, item_id)
        if final_item is not None:
            repository.upsert_flat_item(
                final_item,
                event_type="detail_analysis_completed",
                event_payload={
                    "source": "detail_analysis_worker",
                    "item_id": item_id,
                    "final_json_path": str(final_json_path),
                    "selected_json_path": str(selected_json_path),
                    "raw_artifacts": seed.get("_raw_detail_artifacts"),
                    "analysis_module_b": module_b_receipt,
                },
            )
        repository.mark_seed_detail_completed(
            item_id,
            final_json_path=str(final_json_path),
            selected_json_path=str(selected_json_path),
        )
        summary = {
            "decision": "detail_analysis_completed",
            "item_id": item_id,
            "selected": selected,
            "final_json_path": str(final_json_path),
            "selected_json_path": str(selected_json_path),
            "staged_raw_artifacts": staged_artifacts,
            "counts": repository.seed_queue_counts(),
        }
        _write_runtime_summary(config.output_dir, summary)
        return summary
    except Exception as exc:
        _record_analysis_module_b_receipt(
            repository,
            item_id=item_id,
            receipt=_load_analysis_module_b_latest(config.output_dir, item_id),
        )
        if _is_llm_backend_unavailable_error(exc):
            backend_error = "LLM backend unavailable; " + safe_exception_text(exc)
            repository.mark_seed_detail_analysis_failed(
                item_id,
                backend_error,
                retryable=True,
                revert_attempt=True,
                restore_raw=True,
            )
            summary = {
                "decision": "detail_analysis_backend_unavailable",
                "item_id": item_id,
                "error": backend_error,
                "traceback": safe_exception_traceback(exc),
                "counts": repository.seed_queue_counts(),
            }
            _write_runtime_summary(config.output_dir, summary)
            return summary
        repository.mark_seed_detail_analysis_failed(item_id, safe_exception_text(exc), retryable=True)
        summary = {
            "decision": "detail_analysis_retryable_failure",
            "item_id": item_id,
            "error": safe_exception_text(exc),
            "traceback": safe_exception_traceback(exc),
            "counts": repository.seed_queue_counts(),
        }
        _write_runtime_summary(config.output_dir, summary)
        return summary


__all__ = (
    'run_detail_worker_once',
    'run_detail_analysis_once',
)
