from __future__ import annotations
from tools.live_smoke_context import *  # noqa: F401,F403
from tools.live_smoke_resume import *  # noqa: F401,F403
from tools.live_smoke_list import *  # noqa: F401,F403
from tools.live_smoke_area import *  # noqa: F401,F403
from tools.live_smoke_auth import *  # noqa: F401,F403
from tools.live_smoke_cdp import *  # noqa: F401,F403
from tools.live_smoke_browser import *  # noqa: F401,F403
from tools.live_smoke_summary import *  # noqa: F401,F403
from tools.live_smoke_analysis_config import *  # noqa: F401,F403
from tools.live_smoke_analysis import *  # noqa: F401,F403
from tools.live_smoke_runtime import *  # noqa: F401,F403


def write_followup_from_summary(summary_path: Path, *, output_dir: Path, write_followup_only: bool) -> int:
    summary = load_json(summary_path)
    if isinstance(summary, dict):
        summary.setdefault("summary_path", str(summary_path))
    else:
        raise RuntimeError(f"summary must be a JSON object: {summary_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched = attach_area_artifacts(summary, output_dir=output_dir)
    queue = build_area_followup_queue(enriched, artifact_root=output_dir)
    queue_path = output_dir / "area_followup_queue.json"
    write_json(queue_path, queue)
    if not write_followup_only:
        write_json(output_dir / "summary.json", enriched)
    print(
        json.dumps(
            {
                "summary_path": str(summary_path),
                "area_stats": enriched["area_stats"],
                "area_followup_queue_path": str(queue_path),
                "area_followup_job_count": queue["job_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0

def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a real Taobao judicial-auction detail live smoke.")
    parser.add_argument("--from-summary", type=Path, help="Generate area follow-up artifacts from an existing summary.json without live network crawling.")
    parser.add_argument("--write-followup-only", action="store_true", help="With --from-summary, only write area_followup_queue.json and leave summary.json unchanged.")
    parser.add_argument("--output-dir", type=Path, help="Artifact directory. Defaults to output/live_batch_smoke, or the --from-summary parent.")
    parser.add_argument("--cdp-endpoint", default=os.environ.get("LIVE_BATCH_SMOKE_CDP", DEFAULT_CDP_ENDPOINT))
    parser.add_argument("--url", default=os.environ.get("LIVE_BATCH_SMOKE_URL", DEFAULT_TARGET_URL))
    parser.add_argument(
        "--target-success",
        type=positive_int,
        default=int(os.environ.get("LIVE_BATCH_SMOKE_TARGET", os.environ.get("LIVE_BATCH_SMOKE_LIMIT", "5"))),
    )
    parser.add_argument("--max-attempts", type=positive_int, default=None)
    parser.add_argument("--risk", action="store_true", default=os.environ.get("LIVE_BATCH_SMOKE_RISK", "0") == "1")
    parser.add_argument(
        "--resume-state",
        type=Path,
        default=os.environ.get("LIVE_BATCH_RESUME_STATE"),
        help="Persistent JSON state used to skip already completed item ids.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        default=os.environ.get("LIVE_BATCH_NO_RESUME", "0") == "1",
        help="Disable persistent resume/deduplication state for this run.",
    )
    parser.add_argument("--loop", action="store_true", help="Run batches repeatedly with the same resume state.")
    parser.add_argument("--max-runs", type=positive_int, default=None, help="Stop loop after this many batch runs.")
    parser.add_argument(
        "--loop-interval-seconds",
        type=float,
        default=float(os.environ.get("LIVE_BATCH_LOOP_INTERVAL_SECONDS", "300")),
        help="Sleep interval between looped batch runs.",
    )
    parser.add_argument(
        "--list-st-params",
        default=os.environ.get("LIVE_BATCH_LIST_ST_PARAMS"),
        help="Comma-separated Taobao list sort parameters to union before detail collection, e.g. 2,1,0,3,4,5.",
    )
    parser.add_argument(
        "--list-location-codes",
        default=os.environ.get("LIVE_BATCH_LIST_LOCATION_CODES"),
        help="Comma-separated Taobao location_code values to crawl. Defaults to the --url location_code.",
    )
    parser.add_argument(
        "--list-categories",
        default=os.environ.get("LIVE_BATCH_LIST_CATEGORIES"),
        help="Comma-separated Taobao list category path ids. Defaults to the --url category.",
    )
    parser.add_argument(
        "--list-max-pages",
        type=positive_int,
        default=int(os.environ.get("LIVE_BATCH_LIST_MAX_PAGES", "1")),
        help="Maximum page number to fetch for each location/category/sort combination.",
    )
    parser.add_argument(
        "--list-delay-seconds",
        type=float,
        default=float(os.environ.get("LIVE_BATCH_LIST_DELAY_SECONDS", "8")),
        help="Base delay between list-page requests in a multi-source union.",
    )
    parser.add_argument(
        "--no-list-stop-on-empty",
        action="store_true",
        default=os.environ.get("LIVE_BATCH_LIST_STOP_ON_EMPTY", "1").strip().lower() in {"0", "false", "no", "off"},
        help="Do not stop later pages for a location/category/sort after an empty page is seen.",
    )
    parser.add_argument(
        "--llm-preflight",
        action="store_true",
        default=os.environ.get("LIVE_BATCH_LLM_PREFLIGHT", "0").strip().lower() in {"1", "true", "yes", "on"},
        help="Probe the OpenAI-compatible backend before processing detail items; aborts the batch on connection/TLS/proxy errors.",
    )
    parser.add_argument(
        "--llm-preflight-timeout-seconds",
        type=float,
        default=float(os.environ.get("LIVE_BATCH_LLM_PREFLIGHT_TIMEOUT_SECONDS", "15")),
        help="Timeout for --llm-preflight /models connectivity probe.",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        default=os.environ.get("LIVE_BATCH_RAW_ONLY", project_getenv("CROW_DETAIL_RAW_ONLY", "0")).strip().lower() in TRUE_VALUES,
        help="Fetch and archive raw detail artifacts without invoking the LLM extraction stage.",
    )
    parser.add_argument(
        "--success-delay-seconds",
        type=float,
        default=float(os.environ.get("LIVE_BATCH_SUCCESS_DELAY_SECONDS", "6")),
        help="Base delay between successful detail items.",
    )
    parser.add_argument(
        "--failure-delay-seconds",
        type=float,
        default=float(os.environ.get("LIVE_BATCH_FAILURE_DELAY_SECONDS", "15")),
        help="Base delay after a non-challenge detail failure.",
    )
    parser.add_argument(
        "--pacing-jitter-ratio",
        type=float,
        default=float(os.environ.get("LIVE_BATCH_PACING_JITTER_RATIO", "0.35")),
        help="Symmetric jitter ratio for per-item delays; clamped to 0..1.",
    )
    parser.add_argument(
        "--challenge-cooldown-seconds",
        type=float,
        default=float(os.environ.get("LIVE_BATCH_CHALLENGE_COOLDOWN_SECONDS", "900")),
        help="Recommended cooldown after a detail challenge stops the batch.",
    )
    return parser.parse_args(argv)

def config_from_args(args: argparse.Namespace) -> LiveSmokeConfig:
    from src.collection.adapter_resolver import collection_adapter_from_env

    output_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    max_attempts = args.max_attempts or int(
        os.environ.get("LIVE_BATCH_SMOKE_MAX_ATTEMPTS", str(max(args.target_success * 3, args.target_success)))
    )
    return LiveSmokeConfig(
        output_dir=output_dir,
        cdp_endpoint=args.cdp_endpoint,
        target_url=args.url,
        target_success=args.target_success,
        max_attempts=max_attempts,
        do_risk=bool(args.risk),
        resume_state_path=args.resume_state,
        resume_enabled=not bool(args.no_resume),
        list_st_params=parse_csv_values(args.list_st_params),
        list_location_codes=parse_csv_values(args.list_location_codes),
        list_categories=parse_csv_values(args.list_categories),
        list_max_pages=int(args.list_max_pages),
        list_delay_seconds=max(float(args.list_delay_seconds), 0.0),
        list_stop_on_empty=not bool(args.no_list_stop_on_empty),
        llm_preflight_enabled=bool(args.llm_preflight),
        llm_preflight_timeout_seconds=float(args.llm_preflight_timeout_seconds),
        raw_only=bool(args.raw_only),
        collection_adapter=collection_adapter_from_env(default="taobao_judicial"),
        success_delay_seconds=max(float(args.success_delay_seconds), 0.0),
        failure_delay_seconds=max(float(args.failure_delay_seconds), 0.0),
        pacing_jitter_ratio=min(max(float(args.pacing_jitter_ratio), 0.0), 1.0),
        challenge_cooldown_seconds=max(float(args.challenge_cooldown_seconds), 0.0),
    )

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.from_summary:
        output_dir = args.output_dir or args.from_summary.parent
        return write_followup_from_summary(
            args.from_summary,
            output_dir=output_dir,
            write_followup_only=bool(args.write_followup_only),
        )
    config = config_from_args(args)
    if args.loop:
        loop_summary = run_loop(
            config,
            max_runs=args.max_runs,
            interval_seconds=max(0.0, float(args.loop_interval_seconds)),
        )
        print(json.dumps(loop_summary, ensure_ascii=False, indent=2))
        return 0 if loop_summary["ok"] else 1
    return run_live_smoke(config)

__all__ = ('write_followup_from_summary', 'positive_int', 'parse_args', 'config_from_args', 'main')
