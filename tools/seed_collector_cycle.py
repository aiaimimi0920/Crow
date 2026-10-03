"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.seed_collector_context import *


def _fail_claimed_seed_page(
    config: SeedCollectorConfig,
    repository: PropertyRepository,
    task: dict[str, Any],
    error: str,
) -> bool:
    policy_kwargs = (
        {"worker_id": config.worker_id, "policy": config.seed_scan_policy}
        if config.seed_scan_policy
        else {}
    )
    try:
        repository.fail_seed_scan_page(
            str(task["progress_key"]),
            error,
            retryable=True,
            **policy_kwargs,
        )
    except ValueError:
        if config.seed_scan_policy and config.seed_scan_policy.requires_lease_owner:
            return False
        raise
    return True


def run_seed_collector_once(
    config: SeedCollectorConfig,
    *,
    repository: PropertyRepository,
    http_session: Any,
    browserless_seed_probe: Any,
    ensure_jobs: bool = True,
) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pause_state = _collection_pause_state_with_retry(config.api_base_url)
    auth_probe_summary = None
    if _pause_state_blocks_seed_stage(pause_state):
        if pause_state.get("reason") != "captcha_solver_manual_required":
            summary = {
                "decision": "seed_collection_paused",
                "reason": pause_state.get("reason") or "collection_paused",
                "captcha_solver": pause_state.get("captcha_solver") or {},
                "counts": repository.seed_queue_counts(),
            }
            _write_runtime_summary(config.output_dir, summary)
            return summary
        auth_probe = _probe_seed_auth_state(
            config,
            pause_state,
            http_session=http_session,
            browserless_seed_probe=browserless_seed_probe,
        )
        if auth_probe.get("authenticated"):
            auth_probe_summary = auth_probe
            pause_state = {"paused": False, "reason": "auth_probe_passed", "captcha_solver": pause_state.get("captcha_solver") or {}}
        else:
            summary = {
                "decision": "seed_collection_paused",
                "reason": pause_state.get("reason") or "collection_paused",
                "captcha_solver": pause_state.get("captcha_solver") or {},
                "auth_probe": auth_probe,
                "counts": repository.seed_queue_counts(),
            }
            _write_runtime_summary(config.output_dir, summary)
            return summary

    if ensure_jobs:
        _ensure_seed_scan_jobs(config, repository)
    policy_kwargs = {"policy": config.seed_scan_policy} if config.seed_scan_policy else {}
    if config.breadth_first:
        policy_kwargs["breadth_first"] = True
    task = repository.claim_seed_scan_page(
        config.worker_id,
        lease_seconds=config.lease_seconds,
        parallel_sorts=config.parallel_sorts,
        failure_cooldown_threshold=config.failure_cooldown_threshold,
        failure_cooldown_seconds=config.failure_cooldown_seconds,
        **policy_kwargs,
    )
    if task is None:
        summary = {"decision": "seed_scan_queue_empty", "counts": repository.seed_queue_counts()}
        if auth_probe_summary is not None:
            summary["auth_probe"] = auth_probe_summary
        _write_runtime_summary(config.output_dir, summary)
        return summary

    claimed_summary = {
        "decision": "seed_page_claimed",
        "task": task,
        "counts": repository.seed_queue_counts(),
    }
    if auth_probe_summary is not None:
        claimed_summary["auth_probe"] = auth_probe_summary
    _write_runtime_summary(config.output_dir, claimed_summary)

    page_completed = False
    try:
        adapter = config.collection_adapter or resolve_record_adapter(task)
        list_parser = adapter.create_seed_list_parser(browserless_seed_probe)
        runtime_user_agent = resolve_runtime_user_agent(config.cdp_endpoint)
        html, final_url, status_code, fetch_method = fetch_list_page(
            http_session,
            cdp_endpoint=config.cdp_endpoint,
            target_url=str(task["url"]),
            user_agent=runtime_user_agent or getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT),
            solver_enabled=config.solver_enabled,
            api_base_url=config.api_base_url,
        )
        items, list_summary, has_challenge = _extract_seed_items(
            list_parser,
            html,
            final_url=final_url,
        )
        if has_challenge:
            captcha_solver_report = (
                None
                if config.solver_enabled
                else _report_manual_seed_challenge(config, str(task["url"]))
            )
            _fail_claimed_seed_page(config, repository, task, "list_payload_missing")
            post_challenge_pause_state = _collection_pause_state_with_retry(config.api_base_url)
            if _pause_state_blocks_seed_stage(post_challenge_pause_state):
                summary = {
                    "decision": "seed_collection_paused",
                    "reason": post_challenge_pause_state.get("reason") or "collection_paused",
                    "captcha_solver": post_challenge_pause_state.get("captcha_solver") or {},
                    "task": task,
                    "list_summary": list_summary,
                    "fetch": {
                        "status_code": status_code,
                        "final_url": final_url,
                        "method": fetch_method,
                    },
                    "counts": repository.seed_queue_counts(),
                }
                if auth_probe_summary is not None:
                    summary["auth_probe"] = auth_probe_summary
                if captcha_solver_report is not None:
                    summary["captcha_solver_report"] = captcha_solver_report
                _write_runtime_summary(config.output_dir, summary)
                return summary
            summary = {
                "decision": "seed_page_retryable_failure",
                "reason": "list_challenge_page",
                "task": task,
                "list_summary": list_summary,
                "fetch": {
                    "status_code": status_code,
                    "final_url": final_url,
                    "method": fetch_method,
                },
                "counts": repository.seed_queue_counts(),
            }
            if auth_probe_summary is not None:
                summary["auth_probe"] = auth_probe_summary
            if captcha_solver_report is not None:
                summary["captcha_solver_report"] = captcha_solver_report
            _write_runtime_summary(config.output_dir, summary)
            return summary
        if (
            list_summary.get("has_script") is False
            and list_summary.get("item_count") is None
        ):
            # Transport success alone cannot prove an empty source list.
            missing_reason = (
                "browser_list_payload_missing"
                if str(fetch_method).startswith("browser_page")
                else "list_payload_missing"
            )
            _fail_claimed_seed_page(config, repository, task, missing_reason)
            summary = {
                "decision": "seed_page_retryable_failure",
                "reason": missing_reason,
                "task": task,
                "list_summary": list_summary,
                "fetch": {
                    "status_code": status_code,
                    "final_url": final_url,
                    "method": fetch_method,
                },
                "counts": repository.seed_queue_counts(),
            }
            if auth_probe_summary is not None:
                summary["auth_probe"] = auth_probe_summary
            _write_runtime_summary(config.output_dir, summary)
            return summary

        for item in items:
            if task.get("source_platform"):
                item.setdefault("source_platform", task["source_platform"])
            item.setdefault("source_page_url", final_url)
            item.setdefault("list_location_code", task.get("location_code"))
            item.setdefault("list_category", task.get("category"))
            item.setdefault("list_st_param", task.get("st_param"))
            item.setdefault("list_page", task.get("page"))
            item.setdefault("list_sort_key", task.get("sort_key"))
            item.setdefault("list_sort_name", task.get("sort_name"))

        upsert = repository.upsert_seed_items(
            job_key=str(task["job_key"]),
            progress_key=str(task["progress_key"]),
            sort_key=str(task["sort_key"]),
            sort_name=str(task.get("sort_name") or ""),
            st_param=str(task["st_param"]),
            page=int(task["page"]),
            source_page_url=str(task["url"]),
            source_final_url=final_url,
            items=items,
            **(
                {"policy": config.seed_scan_policy, "worker_id": config.worker_id}
                if config.seed_scan_policy
                else {}
            ),
        )
        has_next = _seed_page_has_next(
            task_page=task.get("page"),
            task_max_page=task.get("max_page", config.max_page),
            list_summary=list_summary,
            filtered_items=items,
        )
        repository.complete_seed_scan_page(
            progress_key=str(task["progress_key"]),
            page=int(task["page"]),
            item_count=len(items),
            has_next=has_next,
            source_url=final_url,
            **(
                {"worker_id": config.worker_id, "policy": config.seed_scan_policy}
                if config.seed_scan_policy
                else {}
            ),
        )
        page_completed = True
        summary = {
            "decision": "seed_page_collected",
            "task": task,
            "fetch": {
                "status_code": status_code,
                "final_url": final_url,
                "method": fetch_method,
            },
            "list_summary": list_summary,
            "item_count": len(items),
            "has_next": has_next,
            "upsert": upsert,
            "counts": repository.seed_queue_counts(),
        }
        if auth_probe_summary is not None:
            summary["auth_probe"] = auth_probe_summary
        _write_runtime_summary(config.output_dir, summary)
        return summary
    except Exception as exc:  # noqa: BLE001 - Release the claim and report every per-page failure.
        if not page_completed:
            _fail_claimed_seed_page(config, repository, task, safe_exception_text(exc))
        if isinstance(exc, CdpEndpointUnavailableError):
            summary = {
                "decision": "seed_collection_paused",
                "reason": "cdp_unreachable",
                "task": task,
                "error": safe_exception_text(exc),
                "traceback": safe_exception_traceback(exc),
                "auth_probe": _build_cdp_unreachable_auth_probe(config, str(task.get("url") or "")),
                "counts": repository.seed_queue_counts(),
            }
            if auth_probe_summary is not None:
                summary["previous_auth_probe"] = auth_probe_summary
            _write_runtime_summary(config.output_dir, summary)
            return summary
        summary = {
            "decision": "seed_page_retryable_failure",
            "reason": "exception",
            "task": task,
            "error": safe_exception_text(exc),
            "traceback": safe_exception_traceback(exc),
            "counts": repository.seed_queue_counts(),
        }
        if auth_probe_summary is not None:
            summary["auth_probe"] = auth_probe_summary
        _write_runtime_summary(config.output_dir, summary)
        return summary


__all__ = (
    '_fail_claimed_seed_page',
    'run_seed_collector_once',
)
