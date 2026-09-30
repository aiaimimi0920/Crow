"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.detail_worker_context import *


def _llm_preflight_is_unavailable(preflight: dict[str, Any] | None) -> bool:
    if not preflight or not preflight.get("enabled"):
        return False
    status_code = preflight.get("status_code")
    chat_status_code = preflight.get("chat_status_code")
    if status_code == 0 or chat_status_code == 0:
        return True
    if isinstance(chat_status_code, int) and chat_status_code < 400:
        return False
    if isinstance(chat_status_code, int) and chat_status_code >= 400:
        return True
    if isinstance(status_code, int) and status_code >= 400:
        return True
    return False


def _llm_preflight_is_retryable(preflight: dict[str, Any] | None) -> bool:
    if not preflight or not preflight.get("enabled"):
        return False
    if preflight.get("error"):
        return True
    chat_status_code = preflight.get("chat_status_code")
    status_code = preflight.get("status_code")
    probe_status = chat_status_code if isinstance(chat_status_code, int) else status_code
    return isinstance(probe_status, int) and (
        probe_status == 0 or probe_status in {408, 425, 429} or probe_status >= 500
    )


def _run_llm_preflight(config: DetailWorkerConfig) -> dict[str, Any] | None:
    max_attempts = max(int(config.llm_preflight_attempts), 1)
    retry_delay_seconds = max(float(config.llm_preflight_retry_delay_seconds), 0.0)
    for attempt in range(1, max_attempts + 1):
        try:
            preflight = preflight_llm_backend(
                timeout=config.llm_preflight_timeout_seconds,
                check_chat=True,
            )
        except Exception as exc:
            preflight = {
                "enabled": True,
                "error": repr(exc),
            }
        if preflight is None:
            return None
        preflight = dict(preflight)
        preflight["attempt"] = attempt
        preflight["max_attempts"] = max_attempts
        unavailable = _llm_preflight_is_unavailable(preflight) or bool(preflight.get("error"))
        if not unavailable:
            return preflight
        if attempt >= max_attempts or not _llm_preflight_is_retryable(preflight):
            return preflight
        time.sleep(retry_delay_seconds * attempt)
    return None


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or default


def _safe_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _safe_non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _safe_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _safe_non_negative_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _live_config(config: DetailWorkerConfig, *, target_url: str) -> LiveSmokeConfig:
    return LiveSmokeConfig(
        output_dir=config.output_dir,
        cdp_endpoint=config.cdp_endpoint,
        target_url=target_url,
        target_success=config.target_success,
        max_attempts=config.max_attempts,
        do_risk=config.do_risk,
        resume_enabled=False,
        llm_preflight_enabled=False,
        raw_only=config.raw_only,
        collection_adapter=config.collection_adapter,
        success_delay_seconds=config.success_delay_seconds,
        failure_delay_seconds=config.failure_delay_seconds,
        pacing_jitter_ratio=config.pacing_jitter_ratio,
        challenge_cooldown_seconds=float(config.challenge_cooldown_seconds),
    )


def _env_flag(name: str, default: bool = False) -> bool:
    raw = project_getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def config_from_env_and_args(argv: Sequence[str] | None = None) -> tuple[DetailWorkerConfig, bool]:
    adapter = collection_adapter_from_env(default="taobao_judicial")
    loop_interval_default = _safe_non_negative_int(project_getenv("CROW_DETAIL_LOOP_INTERVAL_SECONDS"), 900)
    active_loop_interval_default = _safe_non_negative_int(
        project_getenv("CROW_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS"),
        loop_interval_default,
    )
    archive_root_default = project_getenv("CROW_DETAIL_ARCHIVE_ROOT")
    parser = argparse.ArgumentParser(description="DB backed detail worker for legal auction seed URLs.")
    parser.add_argument("--output-dir", type=Path, default=Path(project_getenv("CROW_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR / "detail_worker"))))
    parser.add_argument("--cdp-endpoint", default=project_getenv("CROW_CDP_ENDPOINT", DEFAULT_CDP_ENDPOINT))
    parser.add_argument("--target-success", type=int, default=_safe_int(project_getenv("CROW_DETAIL_TARGET_SUCCESS"), 5))
    parser.add_argument("--max-attempts", type=int, default=_safe_int(project_getenv("CROW_DETAIL_MAX_ATTEMPTS"), 20))
    parser.add_argument("--item-max-attempts", type=int, default=_safe_int(project_getenv("CROW_DETAIL_ITEM_MAX_ATTEMPTS"), 3))
    parser.add_argument(
        "--failure-cooldown-seconds",
        type=int,
        default=_safe_int(project_getenv("CROW_DETAIL_FAILURE_COOLDOWN_SECONDS"), 0),
        help="Skip recently failed detail items for this many seconds before retrying them.",
    )
    parser.add_argument(
        "--success-delay-seconds",
        type=float,
        default=_safe_non_negative_float(project_getenv("CROW_DETAIL_SUCCESS_DELAY_SECONDS"), 6.0),
        help="Base delay between successful collection items in the same batch.",
    )
    parser.add_argument(
        "--failure-delay-seconds",
        type=float,
        default=_safe_non_negative_float(project_getenv("CROW_DETAIL_FAILURE_DELAY_SECONDS"), 15.0),
        help="Base backoff between failed collection items in the same batch.",
    )
    parser.add_argument(
        "--pacing-jitter-ratio",
        type=float,
        default=_safe_non_negative_float(project_getenv("CROW_DETAIL_PACING_JITTER_RATIO"), 0.35),
        help="Symmetric jitter ratio for per-item delays; clamped to the range 0..1.",
    )
    parser.add_argument(
        "--challenge-cooldown-seconds",
        type=int,
        default=_safe_non_negative_int(project_getenv("CROW_DETAIL_CHALLENGE_COOLDOWN_SECONDS"), 900),
        help="Minimum delay before a looped worker resumes after a challenge page.",
    )
    parser.add_argument("--worker-id", default=project_getenv("CROW_DETAIL_WORKER_ID", f"detail-{os.getpid()}"))
    parser.add_argument("--lease-seconds", type=int, default=_safe_int(project_getenv("CROW_DETAIL_LEASE_SECONDS"), 900))
    parser.add_argument("--loop", action="store_true", default=_env_flag("CROW_DETAIL_LOOP", False))
    parser.add_argument("--loop-interval-seconds", type=int, default=loop_interval_default)
    parser.add_argument("--active-loop-interval-seconds", type=int, default=active_loop_interval_default)
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--risk", action="store_true", default=_env_flag("CROW_ENABLE_RISK", False))
    parser.add_argument("--llm-preflight", action="store_true", default=_env_flag("CROW_LLM_PREFLIGHT", False))
    parser.add_argument(
        "--raw-only",
        action="store_true",
        default=_env_flag("CROW_DETAIL_RAW_ONLY", False),
        help="Archive raw detail artifacts without running AI extraction or finalizing flat items.",
    )
    parser.add_argument(
        "--analysis-only",
        action="store_true",
        default=_env_flag("CROW_DETAIL_ANALYSIS_ONLY", False)
        or (project_getenv("CROW_RUN_MODE", "").strip().lower() in {"detail-analysis-worker", "detail-analysis-batch"}),
        help="Consume previously captured raw detail artifacts and run only the AI finalization stage.",
    )
    parser.add_argument("--api-base-url", default=project_getenv("CROW_API_BASE_URL", ""))
    parser.add_argument(
        "--detail-archive-root",
        type=Path,
        default=(Path(archive_root_default) if archive_root_default else None),
        help="raw detail HTML 持久归档根目录；不设则不归档",
    )
    parser.add_argument(
        "--solver-enabled",
        "--captcha-solver-enabled",
        action="store_true",
        default=captcha_solver_enabled(default=False),
        help="Report Taobao detail challenge pages to the configured captcha solver queue.",
    )
    parser.add_argument(
        "--manual-challenge-reporting",
        action="store_true",
        default=_env_flag("CROW_MANUAL_CHALLENGE_REPORTING", False),
        help="Pause collection and request PC1 manual authentication without starting the automatic solver.",
    )
    parser.add_argument(
        "--llm-preflight-timeout-seconds",
        type=float,
        default=_safe_float(project_getenv("CROW_LLM_PREFLIGHT_TIMEOUT_SECONDS"), 15.0),
    )
    parser.add_argument(
        "--llm-preflight-attempts",
        type=int,
        default=_safe_int(project_getenv("CROW_LLM_PREFLIGHT_ATTEMPTS"), 3),
    )
    parser.add_argument(
        "--llm-preflight-retry-delay-seconds",
        type=float,
        default=_safe_non_negative_float(project_getenv("CROW_LLM_PREFLIGHT_RETRY_DELAY_SECONDS"), 2.0),
    )
    args = parser.parse_args(argv)
    if args.max_runs is None and project_getenv("CROW_DETAIL_MAX_RUNS"):
        args.max_runs = _safe_int(project_getenv("CROW_DETAIL_MAX_RUNS"), 1)
    analysis_only = bool(args.analysis_only)
    return (
        DetailWorkerConfig(
            output_dir=args.output_dir,
            cdp_endpoint=_clean_text(args.cdp_endpoint, DEFAULT_CDP_ENDPOINT),
            target_success=max(int(args.target_success), 1),
            max_attempts=max(int(args.max_attempts), 1),
            worker_id=_clean_text(args.worker_id, f"detail-{os.getpid()}"),
            do_risk=bool(args.risk),
            lease_seconds=max(int(args.lease_seconds), 1),
            item_max_attempts=max(int(args.item_max_attempts), 1),
            failure_cooldown_seconds=max(int(args.failure_cooldown_seconds), 0),
            success_delay_seconds=max(float(args.success_delay_seconds), 0.0),
            failure_delay_seconds=max(float(args.failure_delay_seconds), 0.0),
            pacing_jitter_ratio=min(max(float(args.pacing_jitter_ratio), 0.0), 1.0),
            challenge_cooldown_seconds=max(int(args.challenge_cooldown_seconds), 0),
            loop_interval_seconds=max(int(args.loop_interval_seconds), 0),
            active_loop_interval_seconds=max(int(args.active_loop_interval_seconds), 0),
            max_runs=args.max_runs,
            llm_preflight_enabled=bool(args.llm_preflight),
            llm_preflight_timeout_seconds=max(float(args.llm_preflight_timeout_seconds), 1.0),
            llm_preflight_attempts=max(int(args.llm_preflight_attempts), 1),
            llm_preflight_retry_delay_seconds=max(float(args.llm_preflight_retry_delay_seconds), 0.0),
            solver_enabled=bool(args.solver_enabled),
            api_base_url=_clean_text(args.api_base_url),
            raw_only=False if analysis_only else bool(args.raw_only),
            analysis_only=analysis_only,
            manual_challenge_reporting=bool(args.manual_challenge_reporting),
            detail_archive_root=args.detail_archive_root,
            collection_adapter=adapter,
        ),
        bool(args.loop),
    )


__all__ = (
    '_llm_preflight_is_unavailable',
    '_llm_preflight_is_retryable',
    '_run_llm_preflight',
    '_clean_text',
    '_safe_int',
    '_safe_non_negative_int',
    '_safe_float',
    '_safe_non_negative_float',
    '_live_config',
    '_env_flag',
    'config_from_env_and_args',
)
