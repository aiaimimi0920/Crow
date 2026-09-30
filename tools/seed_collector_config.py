"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.seed_collector_context import *


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
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_seed_sort_specs(raw: str | None) -> tuple[SeedSortSpec, ...]:
    text = _clean_text(raw, DEFAULT_SEED_SORTS)
    specs: list[SeedSortSpec] = []
    seen_keys: set[str] = set()
    for index, chunk in enumerate(text.replace(";", ",").split(",")):
        value = chunk.strip()
        if not value:
            continue
        parts = [part.strip() for part in value.split(":", 2)]
        if len(parts) == 1:
            sort_key = f"sort_{parts[0]}"
            st_param = parts[0]
            sort_name = sort_key
        elif len(parts) == 2:
            sort_key, st_param = parts
            sort_name = sort_key
        else:
            sort_key, st_param, sort_name = parts
        sort_key = sort_key or f"sort_{index}"
        st_param = st_param or sort_key
        sort_name = sort_name or sort_key
        if sort_key in seen_keys:
            continue
        seen_keys.add(sort_key)
        specs.append(SeedSortSpec(sort_key=sort_key, st_param=st_param, sort_name=sort_name, sort_order=len(specs)))
    if not specs:
        raise ValueError("at least one seed sort spec is required")
    return tuple(specs)


def _safe_sort_order(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_seed_sort_specs_value(value: Any, fallback: tuple[SeedSortSpec, ...]) -> tuple[SeedSortSpec, ...]:
    if isinstance(value, str):
        return parse_seed_sort_specs(value)
    if not isinstance(value, list):
        return fallback
    specs: list[SeedSortSpec] = []
    seen_keys: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        sort_key = _clean_text(item.get("sort_key") or item.get("key") or item.get("st_param"), f"sort_{index}")
        st_param = _clean_text(item.get("st_param") or item.get("value"), sort_key)
        sort_name = _clean_text(item.get("sort_name") or item.get("name"), sort_key)
        if sort_key in seen_keys:
            continue
        seen_keys.add(sort_key)
        specs.append(
            SeedSortSpec(
                sort_key=sort_key,
                st_param=st_param,
                sort_name=sort_name,
                sort_order=_safe_sort_order(item.get("sort_order"), len(specs)),
            )
        )
    return tuple(sorted(specs, key=lambda spec: (spec.sort_order, spec.sort_key))) if specs else fallback


def parse_seed_job_specs(
    raw_jobs: Any,
    *,
    fallback_sort_specs: tuple[SeedSortSpec, ...],
    fallback_max_page: int,
    fallback_source_url_template: str = "",
    fallback_category: str = DEFAULT_SEED_CATEGORY,
    requires_location_code: bool = True,
) -> tuple[SeedScanJobSpec, ...]:
    if raw_jobs in (None, ""):
        return ()
    if isinstance(raw_jobs, str):
        decoded = json.loads(raw_jobs)
    else:
        decoded = raw_jobs
    if not isinstance(decoded, list):
        raise ValueError("seed jobs must be a JSON array")
    jobs: list[SeedScanJobSpec] = []
    for index, item in enumerate(decoded):
        if not isinstance(item, dict):
            continue
        location_code = _clean_text(item.get("location_code"))
        if not location_code and requires_location_code:
            raise ValueError(f"seed job at index {index} requires location_code")
        location_code = location_code or "source"
        category = _clean_text(item.get("category"), fallback_category)
        sort_specs = _parse_seed_sort_specs_value(
            item.get("sorts") if "sorts" in item else item.get("sort_specs"),
            fallback_sort_specs,
        )
        max_page = _safe_int(item.get("max_page"), fallback_max_page)
        fallback_key = f"{location_code}-{category}"
        jobs.append(
            SeedScanJobSpec(
                job_key=_clean_text(item.get("job_key"), fallback_key),
                province=_clean_text(item.get("province")),
                city=_clean_text(item.get("city")),
                district=_clean_text(item.get("district")),
                location_code=location_code,
                category=category,
                sort_specs=sort_specs,
                max_page=max_page,
                source_url_template=_clean_text(
                    item.get("source_url_template") or item.get("url_template"),
                    fallback_source_url_template,
                ),
            )
        )
    return tuple(jobs)


def config_from_env_and_args(argv: Sequence[str] | None = None) -> tuple[SeedCollectorConfig, bool]:
    adapter = collection_adapter_from_env(default="taobao_judicial")
    seed_scan_policy = adapter.seed_scan_policy
    generic_defaults = not seed_scan_policy.requires_location_code
    default_job_key = f"{adapter.source_platform}-seed" if generic_defaults else DEFAULT_SEED_JOB_KEY
    default_location = "source" if generic_defaults else DEFAULT_SEED_LOCATION_CODE
    default_category = adapter.source_platform if generic_defaults else DEFAULT_SEED_CATEGORY
    default_sorts = "source:source:default" if generic_defaults else DEFAULT_SEED_SORTS
    default_max_page = 1 if generic_defaults else 83
    source_url_template_default = project_getenv("CROW_SEED_SOURCE_URL_TEMPLATE", "")
    loop_interval_default = _safe_non_negative_int(project_getenv("CROW_SEED_LOOP_INTERVAL_SECONDS"), 1800)
    active_loop_interval_default = _safe_non_negative_int(
        project_getenv("CROW_SEED_ACTIVE_LOOP_INTERVAL_SECONDS"),
        loop_interval_default,
    )
    auth_probe_interval_default = _safe_non_negative_int(
        project_getenv("CROW_SEED_AUTH_PROBE_INTERVAL_SECONDS"),
        DEFAULT_AUTH_PROBE_INTERVAL_SECONDS,
    )
    parser = argparse.ArgumentParser(description="DB-backed rough-collection page scanner.")
    parser.add_argument("--job-key", default=project_getenv("CROW_SEED_JOB_KEY", default_job_key))
    parser.add_argument("--province", default=project_getenv("CROW_SEED_PROVINCE", "" if generic_defaults else "广东省"))
    parser.add_argument("--city", default=project_getenv("CROW_SEED_CITY", "" if generic_defaults else "广州市"))
    parser.add_argument("--district", default=project_getenv("CROW_SEED_DISTRICT", "" if generic_defaults else "南沙区"))
    parser.add_argument("--location-code", default=project_getenv("CROW_SEED_LOCATION_CODE", default_location))
    parser.add_argument("--category", default=project_getenv("CROW_SEED_CATEGORY", default_category))
    parser.add_argument("--sorts", default=project_getenv("CROW_SEED_SORTS", default_sorts))
    parser.add_argument("--max-page", type=int, default=_safe_int(project_getenv("CROW_SEED_MAX_PAGE"), default_max_page))
    parser.add_argument("--source-url-template", default=source_url_template_default)
    parser.add_argument("--cdp-endpoint", default=project_getenv("CROW_CDP_ENDPOINT", DEFAULT_CDP_ENDPOINT))
    parser.add_argument("--output-dir", type=Path, default=Path(project_getenv("CROW_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR / "seed_collector"))))
    parser.add_argument("--worker-id", default=project_getenv("CROW_SEED_WORKER_ID", f"seed-{os.getpid()}"))
    parser.add_argument("--lease-seconds", type=int, default=_safe_int(project_getenv("CROW_SEED_LEASE_SECONDS"), 120))
    parser.add_argument("--loop", action="store_true", default=project_getenv("CROW_SEED_LOOP", "").lower() in {"1", "true", "yes", "on"})
    parser.add_argument("--loop-interval-seconds", type=int, default=loop_interval_default)
    parser.add_argument("--active-loop-interval-seconds", type=int, default=active_loop_interval_default)
    parser.add_argument("--auth-probe-interval-seconds", type=int, default=auth_probe_interval_default)
    parser.add_argument("--pages-per-run", type=int, default=_safe_int(project_getenv("CROW_SEED_PAGES_PER_RUN"), 10))
    parser.add_argument(
        "--page-delay-seconds",
        type=float,
        default=max(_safe_float(project_getenv("CROW_SEED_PAGE_DELAY_SECONDS"), 8.0), 0.0),
        help="Base delay between list-page requests in the same rough-collection cycle.",
    )
    parser.add_argument(
        "--pacing-jitter-ratio",
        type=float,
        default=max(_safe_float(project_getenv("CROW_SEED_PACING_JITTER_RATIO"), 0.35), 0.0),
        help="Symmetric jitter ratio for list-page delays; clamped to 0..1.",
    )
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--api-base-url", default=project_getenv("CROW_API_BASE_URL", ""))
    parser.add_argument("--jobs-file", default=project_getenv("CROW_SEED_JOBS_FILE", ""))
    parser.add_argument("--jobs-json", default=project_getenv("CROW_SEED_JOBS_JSON", ""))
    parser.add_argument(
        "--failure-cooldown-threshold",
        type=int,
        default=_safe_non_negative_int(project_getenv("CROW_SEED_FAILURE_COOLDOWN_THRESHOLD"), 0),
    )
    parser.add_argument(
        "--failure-cooldown-seconds",
        type=int,
        default=_safe_non_negative_int(project_getenv("CROW_SEED_FAILURE_COOLDOWN_SECONDS"), 0),
    )
    parser.add_argument(
        "--parallel-sorts",
        action="store_true",
        default=project_getenv("CROW_SEED_PARALLEL_SORTS", "").lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument(
        "--solver-enabled",
        "--captcha-solver-enabled",
        action="store_true",
        default=captcha_solver_enabled(default=False),
        help="Report Taobao list challenge pages to the configured captcha solver queue.",
    )
    parser.add_argument(
        "--manual-challenge-reporting",
        action="store_true",
        default=project_getenv("CROW_MANUAL_CHALLENGE_REPORTING", "").lower() in {"1", "true", "yes", "on"},
        help="Pause collection and request PC1 manual authentication without starting the automatic solver.",
    )
    args = parser.parse_args(argv)
    if args.max_runs is None and project_getenv("CROW_SEED_MAX_RUNS"):
        args.max_runs = _safe_int(project_getenv("CROW_SEED_MAX_RUNS"), 1)
    sort_specs = parse_seed_sort_specs(args.sorts)
    max_page = max(int(args.max_page), 1)
    jobs_source = ""
    if _clean_text(args.jobs_file):
        jobs_source = Path(args.jobs_file).read_text(encoding="utf-8")
    elif _clean_text(args.jobs_json):
        jobs_source = str(args.jobs_json)
    seed_jobs = parse_seed_job_specs(
        jobs_source,
        fallback_sort_specs=sort_specs,
        fallback_max_page=max_page,
        fallback_source_url_template=_clean_text(args.source_url_template),
        fallback_category=default_category,
        requires_location_code=seed_scan_policy.requires_location_code,
    )

    return (
        SeedCollectorConfig(
            job_key=_clean_text(args.job_key, default_job_key),
            province=_clean_text(args.province),
            city=_clean_text(args.city),
            district=_clean_text(args.district),
            location_code=_clean_text(args.location_code, default_location),
            category=_clean_text(args.category, default_category),
            sort_specs=sort_specs,
            max_page=max_page,
            cdp_endpoint=_clean_text(args.cdp_endpoint, DEFAULT_CDP_ENDPOINT),
            output_dir=args.output_dir,
            worker_id=_clean_text(args.worker_id, f"seed-{os.getpid()}"),
            lease_seconds=max(int(args.lease_seconds), 1),
            loop_interval_seconds=max(int(args.loop_interval_seconds), 0),
            active_loop_interval_seconds=max(int(args.active_loop_interval_seconds), 0),
            auth_probe_interval_seconds=max(int(args.auth_probe_interval_seconds), 0),
            max_runs=args.max_runs,
            pages_per_run=max(int(args.pages_per_run), 1),
            page_delay_seconds=max(float(args.page_delay_seconds), 0.0),
            pacing_jitter_ratio=min(max(float(args.pacing_jitter_ratio), 0.0), 1.0),
            solver_enabled=bool(args.solver_enabled),
            manual_challenge_reporting=bool(args.manual_challenge_reporting),
            api_base_url=_clean_text(args.api_base_url),
            seed_jobs=seed_jobs,
            parallel_sorts=bool(args.parallel_sorts),
            failure_cooldown_threshold=max(int(args.failure_cooldown_threshold), 0),
            failure_cooldown_seconds=max(int(args.failure_cooldown_seconds), 0),
            source_url_template=_clean_text(args.source_url_template),
            seed_scan_policy=seed_scan_policy,
            collection_adapter=adapter,
        ),
        bool(args.loop),
    )


__all__ = (
    '_clean_text',
    '_safe_int',
    '_safe_non_negative_int',
    '_safe_float',
    'parse_seed_sort_specs',
    '_safe_sort_order',
    '_parse_seed_sort_specs_value',
    'parse_seed_job_specs',
    'config_from_env_and_args',
)
