from __future__ import annotations

import os
import subprocess
import sys
import importlib.util
import warnings
from pathlib import Path
from typing import Mapping

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import SAWarning


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_environment import getenv as project_getenv

TRUE_VALUES = {"1", "true", "yes", "y", "on"}
CAPTCHA_SOLVER_ENV_KEYS = (
    "FAPAI_CAPTCHA_SOLVER_ENABLED",
    "FAPAI_SOLVER_ENABLED",
    "SOLVER_ENABLED",
    "solver_enabled",
)
SEED_CAPTCHA_SOLVER_ENV_KEYS = ("FAPAI_SEED_CAPTCHA_SOLVER_ENABLED",) + CAPTCHA_SOLVER_ENV_KEYS
DETAIL_CAPTCHA_SOLVER_ENV_KEYS = ("FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED",) + CAPTCHA_SOLVER_ENV_KEYS


def _normalize_node_id(value: str | None) -> str | None:
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value or "").strip())
    normalized = normalized.strip("-_")
    return normalized or None


def _node_scoped_output_dir(env: Mapping[str, str], output_dir: str | None, default: str) -> str:
    raw_output_dir = str(output_dir or default)
    node_id = _normalize_node_id(env_text(env, "CROW_NODE_ID"))
    if not node_id or env_flag(env, "CROW_DISABLE_NODE_OUTPUT_SCOPE", False):
        return raw_output_dir

    normalized = raw_output_dir.replace("\\", "/").rstrip("/")
    node_segment = f"/nodes/{node_id}/"
    if node_segment in f"{normalized}/":
        return normalized
    if normalized == "/data/output":
        leaf = "default"
    else:
        leaf = normalized.rsplit("/", 1)[-1] or "default"
    return f"/data/output/nodes/{node_id}/{leaf}"


def _node_scoped_worker_id(
    env: Mapping[str, str],
    worker_id: str | None,
    default_without_node: str | None = None,
) -> str | None:
    raw_worker_id = env_text({"value": worker_id or ""}, "value", default_without_node)
    node_id = _normalize_node_id(env_text(env, "CROW_NODE_ID"))
    if not raw_worker_id:
        return None
    if not node_id or env_flag(env, "CROW_DISABLE_NODE_WORKER_SCOPE", False):
        return raw_worker_id
    if raw_worker_id == node_id or raw_worker_id.startswith(f"{node_id}-"):
        return raw_worker_id
    return f"{node_id}-{raw_worker_id}"


def env_text(env: Mapping[str, str], key: str, default: str | None = None) -> str | None:
    value = project_getenv(key, reader=env.get)
    if value is None:
        return default
    normalized = str(value).strip()
    return normalized if normalized else default


def env_flag(env: Mapping[str, str], key: str, default: bool = False) -> bool:
    value = env_text(env, key)
    if value is None:
        return default
    return value.lower() in TRUE_VALUES


def any_env_flag(env: Mapping[str, str], keys: tuple[str, ...], default: bool = False) -> bool:
    for key in keys:
        value = env_text(env, key)
        if value is not None:
            return value.lower() in TRUE_VALUES
    return default


def append_option(command: list[str], option: str, value: str | None) -> None:
    if value is not None:
        command.extend([option, value])


def build_live_command(env: Mapping[str, str]) -> list[str]:
    run_mode = (env_text(env, "CROW_RUN_MODE", "live-loop") or "live-loop").lower()
    output_dir = _node_scoped_output_dir(env, env_text(env, "CROW_OUTPUT_DIR", "/data/output/live_batch_smoke"), "/data/output/live_batch_smoke")
    resume_state = env_text(env, "CROW_RESUME_STATE", f"{output_dir}/resume_state.json")

    command = [
        sys.executable,
        "tools/live_batch_smoke.py",
        "--output-dir",
        str(output_dir),
        "--cdp-endpoint",
        env_text(env, "CROW_CDP_ENDPOINT", "http://host.docker.internal:9223") or "http://host.docker.internal:9223",
        "--url",
        env_text(env, "CROW_TARGET_URL", "https://sf.taobao.com/list/50025969__2.htm?location_code=110101&st_param=2&auction_start_seg=-1&page=1")
        or "",
        "--target-success",
        env_text(env, "CROW_TARGET_SUCCESS", "5") or "5",
        "--max-attempts",
        env_text(env, "CROW_MAX_ATTEMPTS", "50") or "50",
    ]

    if env_flag(env, "CROW_ENABLE_RISK", False):
        command.append("--risk")
    live_raw_only = env_flag(env, "LIVE_BATCH_RAW_ONLY", env_flag(env, "CROW_DETAIL_RAW_ONLY", False))
    if live_raw_only:
        command.append("--raw-only")
    if env_flag(env, "CROW_DISABLE_RESUME", False):
        command.append("--no-resume")
    else:
        append_option(command, "--resume-state", resume_state)

    append_option(command, "--list-st-params", env_text(env, "CROW_LIST_ST_PARAMS", "2,1,0,3,4,5"))
    append_option(command, "--list-location-codes", env_text(env, "CROW_LIST_LOCATION_CODES"))
    append_option(command, "--list-categories", env_text(env, "CROW_LIST_CATEGORIES"))
    append_option(command, "--list-max-pages", env_text(env, "CROW_LIST_MAX_PAGES", "83"))
    if not env_flag(env, "CROW_LIST_STOP_ON_EMPTY", True):
        command.append("--no-list-stop-on-empty")
    if env_flag(env, "CROW_LLM_PREFLIGHT", True) and not live_raw_only:
        command.append("--llm-preflight")
        append_option(command, "--llm-preflight-timeout-seconds", env_text(env, "CROW_LLM_PREFLIGHT_TIMEOUT_SECONDS", "15"))

    if run_mode == "live-loop":
        command.append("--loop")
        append_option(command, "--loop-interval-seconds", env_text(env, "CROW_LOOP_INTERVAL_SECONDS", "300"))
        append_option(command, "--max-runs", env_text(env, "CROW_MAX_RUNS"))
    return command


def build_api_command(env: Mapping[str, str]) -> list[str]:
    cert_file = env_text(env, "CROW_API_TLS_CERT_FILE")
    key_file = env_text(env, "CROW_API_TLS_KEY_FILE")
    if bool(cert_file) != bool(key_file):
        raise ValueError("Collection API TLS requires both certificate and key files")
    command = [
        sys.executable,
        "tools/run_isolated_collection_api.py",
        "--port",
        env_text(env, "CROW_API_PORT", "8001") or "8001",
    ]
    append_option(command, "--db-url", env_text(env, "CROW_DB_URL"))
    append_option(command, "--tls-cert-file", cert_file)
    append_option(command, "--tls-key-file", key_file)
    raw_codes = env_text(env, "CROW_SEED_LOCATION_CODES")
    if raw_codes:
        for code in raw_codes.replace(";", ",").split(","):
            normalized = code.strip()
            if normalized:
                command.extend(["--seed-location-code", normalized])
    return command


def build_area_followup_command(env: Mapping[str, str]) -> list[str]:
    output_dir = _node_scoped_output_dir(env, env_text(env, "CROW_OUTPUT_DIR", "/data/output/live_batch_smoke"), "/data/output/live_batch_smoke")
    command = [
        sys.executable,
        "tools/area_followup_runner.py",
        "--queue",
        env_text(env, "CROW_AREA_QUEUE", f"{output_dir}/area_followup_queue.json") or "",
        "--output-dir",
        str(output_dir),
    ]
    append_option(command, "--cdp-endpoint", env_text(env, "CROW_CDP_ENDPOINT"))
    if env_flag(env, "CROW_AREA_APPLY_PATCHES", False):
        command.append("--apply-patches")
    append_option(command, "--push-area-result", env_text(env, "CROW_AREA_PUSH_URL"))
    return command


def build_seed_collector_command(env: Mapping[str, str]) -> list[str]:
    output_dir = _node_scoped_output_dir(
        env,
        env_text(env, "CROW_OUTPUT_DIR", "/data/output/seed_collector"),
        "/data/output/seed_collector",
    )
    worker_id = _node_scoped_worker_id(env, env_text(env, "CROW_SEED_WORKER_ID"), "seed-1" if env_text(env, "CROW_NODE_ID") else None)
    command = [
        sys.executable,
        "tools/seed_collector.py",
        "--output-dir",
        output_dir,
        "--cdp-endpoint",
        env_text(env, "CROW_CDP_ENDPOINT", "http://host.docker.internal:9223") or "http://host.docker.internal:9223",
        "--job-key",
        env_text(env, "CROW_SEED_JOB_KEY", "guangdong-guangzhou-nansha-50025969") or "guangdong-guangzhou-nansha-50025969",
        "--province",
        env_text(env, "CROW_SEED_PROVINCE", "广东省") or "广东省",
        "--city",
        env_text(env, "CROW_SEED_CITY", "广州市") or "广州市",
        "--district",
        env_text(env, "CROW_SEED_DISTRICT", "南沙区") or "南沙区",
        "--location-code",
        env_text(env, "CROW_SEED_LOCATION_CODE", "440115") or "440115",
        "--category",
        env_text(env, "CROW_SEED_CATEGORY", "50025969") or "50025969",
        "--sorts",
        env_text(
            env,
            "CROW_SEED_SORTS",
            "sort_0:0:默认排序,sort_3:3:价格由高到低,bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远,sort_4:4:排序4,sort_5:5:排序5",
        )
        or "",
        "--max-page",
        env_text(env, "CROW_SEED_MAX_PAGE", env_text(env, "CROW_LIST_MAX_PAGES", "83")) or "83",
    ]
    append_option(command, "--worker-id", worker_id)
    append_option(command, "--lease-seconds", env_text(env, "CROW_SEED_LEASE_SECONDS"))
    append_option(command, "--pages-per-run", env_text(env, "CROW_SEED_PAGES_PER_RUN", "10"))
    append_option(command, "--api-base-url", env_text(env, "CROW_API_BASE_URL"))
    append_option(command, "--jobs-file", env_text(env, "CROW_SEED_JOBS_FILE"))
    append_option(command, "--jobs-json", env_text(env, "CROW_SEED_JOBS_JSON"))
    append_option(command, "--failure-cooldown-threshold", env_text(env, "CROW_SEED_FAILURE_COOLDOWN_THRESHOLD"))
    append_option(command, "--failure-cooldown-seconds", env_text(env, "CROW_SEED_FAILURE_COOLDOWN_SECONDS"))
    if env_flag(env, "CROW_SEED_PARALLEL_SORTS", False):
        command.append("--parallel-sorts")
    if any_env_flag(env, SEED_CAPTCHA_SOLVER_ENV_KEYS, False):
        command.append("--solver-enabled")
    if (env_text(env, "CROW_RUN_MODE", "seed-collector") or "").lower() == "seed-collector":
        command.append("--loop")
        loop_interval_seconds = env_text(env, "CROW_SEED_LOOP_INTERVAL_SECONDS", env_text(env, "CROW_LOOP_INTERVAL_SECONDS", "1800"))
        active_loop_interval_seconds = env_text(
            env,
            "CROW_SEED_ACTIVE_LOOP_INTERVAL_SECONDS",
            env_text(env, "CROW_ACTIVE_LOOP_INTERVAL_SECONDS", loop_interval_seconds),
        )
        append_option(command, "--loop-interval-seconds", loop_interval_seconds)
        append_option(command, "--active-loop-interval-seconds", active_loop_interval_seconds)
        append_option(command, "--max-runs", env_text(env, "CROW_SEED_MAX_RUNS"))
    return command


def build_detail_worker_command(env: Mapping[str, str]) -> list[str]:
    run_mode = (env_text(env, "CROW_RUN_MODE", "detail-worker") or "detail-worker").lower()
    analysis_only = run_mode in {"detail-analysis-worker", "detail-analysis-batch"} or env_flag(
        env, "CROW_DETAIL_ANALYSIS_ONLY", False
    )
    target_success = env_text(env, "CROW_DETAIL_TARGET_SUCCESS", env_text(env, "CROW_TARGET_SUCCESS", "5"))
    max_attempts = env_text(env, "CROW_DETAIL_MAX_ATTEMPTS", env_text(env, "CROW_MAX_ATTEMPTS", "20"))
    item_max_attempts = env_text(env, "CROW_DETAIL_ITEM_MAX_ATTEMPTS", "3")
    loop_interval_seconds = env_text(env, "CROW_DETAIL_LOOP_INTERVAL_SECONDS", env_text(env, "CROW_LOOP_INTERVAL_SECONDS", "900"))
    active_loop_interval_seconds = env_text(
        env,
        "CROW_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS",
        env_text(env, "CROW_ACTIVE_LOOP_INTERVAL_SECONDS", loop_interval_seconds),
    )
    max_runs = env_text(env, "CROW_DETAIL_MAX_RUNS")
    llm_preflight = env_flag(env, "CROW_LLM_PREFLIGHT", True)
    llm_preflight_timeout_seconds = env_text(env, "CROW_LLM_PREFLIGHT_TIMEOUT_SECONDS", "15")
    if analysis_only:
        target_success = env_text(env, "CROW_DETAIL_ANALYSIS_TARGET_SUCCESS", target_success)
        max_attempts = env_text(env, "CROW_DETAIL_ANALYSIS_MAX_ATTEMPTS", max_attempts)
        item_max_attempts = env_text(env, "CROW_DETAIL_ANALYSIS_ITEM_MAX_ATTEMPTS", item_max_attempts)
        loop_interval_seconds = env_text(env, "CROW_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS", loop_interval_seconds)
        active_loop_interval_seconds = env_text(
            env,
            "CROW_DETAIL_ANALYSIS_ACTIVE_LOOP_INTERVAL_SECONDS",
            env_text(
                env,
                "CROW_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS",
                env_text(env, "CROW_ACTIVE_LOOP_INTERVAL_SECONDS", loop_interval_seconds),
            ),
        )
        max_runs = env_text(env, "CROW_DETAIL_ANALYSIS_MAX_RUNS", max_runs)
        llm_preflight = env_flag(env, "CROW_ANALYSIS_LLM_PREFLIGHT", llm_preflight)
        llm_preflight_timeout_seconds = env_text(
            env,
            "CROW_ANALYSIS_LLM_PREFLIGHT_TIMEOUT_SECONDS",
            llm_preflight_timeout_seconds,
        )
    output_dir = _node_scoped_output_dir(
        env,
        env_text(env, "CROW_OUTPUT_DIR", "/data/output/detail_worker"),
        "/data/output/detail_worker",
    )
    default_worker_id = "analysis-1" if analysis_only else "detail-1"
    worker_id = _node_scoped_worker_id(
        env,
        env_text(env, "CROW_DETAIL_WORKER_ID"),
        default_worker_id if env_text(env, "CROW_NODE_ID") else None,
    )
    detail_cdp_endpoint = (
        env_text(env, "CROW_DETAIL_CDP_ENDPOINT")
        or env_text(env, "CROW_CDP_ENDPOINT", "http://host.docker.internal:9223")
        or "http://host.docker.internal:9223"
    )
    command = [
        sys.executable,
        "tools/detail_worker.py",
        "--output-dir",
        output_dir,
        "--cdp-endpoint",
        detail_cdp_endpoint,
        "--target-success",
        target_success or "5",
        "--max-attempts",
        max_attempts or "20",
        "--item-max-attempts",
        item_max_attempts or "3",
    ]
    append_option(command, "--worker-id", worker_id)
    append_option(command, "--lease-seconds", env_text(env, "CROW_DETAIL_LEASE_SECONDS"))
    append_option(command, "--failure-cooldown-seconds", env_text(env, "CROW_DETAIL_FAILURE_COOLDOWN_SECONDS"))
    append_option(command, "--api-base-url", env_text(env, "CROW_API_BASE_URL"))
    append_option(command, "--detail-archive-root", env_text(env, "CROW_DETAIL_ARCHIVE_ROOT"))
    raw_only = False if analysis_only else env_flag(env, "CROW_DETAIL_RAW_ONLY", False)
    if analysis_only:
        command.append("--analysis-only")
    if raw_only:
        command.append("--raw-only")
    if any_env_flag(env, DETAIL_CAPTCHA_SOLVER_ENV_KEYS, False) and not analysis_only:
        command.append("--solver-enabled")
    if env_flag(env, "CROW_ENABLE_RISK", False):
        command.append("--risk")
    if llm_preflight and not raw_only:
        command.append("--llm-preflight")
        append_option(command, "--llm-preflight-timeout-seconds", llm_preflight_timeout_seconds)
    if run_mode in {"detail-worker", "detail-analysis-worker"}:
        command.append("--loop")
        append_option(command, "--loop-interval-seconds", loop_interval_seconds)
        append_option(command, "--active-loop-interval-seconds", active_loop_interval_seconds)
        append_option(command, "--max-runs", max_runs)
    return command


def build_command(env: Mapping[str, str]) -> list[str]:
    mode = (env_text(env, "CROW_RUN_MODE", "live-loop") or "live-loop").lower()
    if mode in {"api", "server"}:
        return build_api_command(env)
    if mode == "area-followup":
        return build_area_followup_command(env)
    if mode in {"seed-collector", "seed-batch"}:
        return build_seed_collector_command(env)
    if mode in {"detail-worker", "detail-batch", "detail-analysis-worker", "detail-analysis-batch"}:
        return build_detail_worker_command(env)
    if mode in {"live-loop", "live-batch"}:
        return build_live_command(env)
    if mode == "sleep":
        return ["sleep", "infinity"]
    raise ValueError(f"Unsupported CROW_RUN_MODE: {mode}")


def _load_storage_model_metadata():
    module_name = "_fapaifang_storage_models_for_entrypoint"
    loaded = sys.modules.get(module_name)
    if loaded is not None:
        return loaded.Base.metadata

    model_path = REPO_ROOT / "src" / "storage" / "models.py"
    spec = importlib.util.spec_from_file_location(module_name, model_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load storage models from {model_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module.Base.metadata


def _expected_database_schema() -> dict[str, set[str]]:
    metadata = _load_storage_model_metadata()
    return {table.name: {column.name for column in table.columns} for table in metadata.sorted_tables}


def _actual_database_schema(db_url: str) -> dict[str, set[str]]:
    engine = create_engine(db_url, future=True)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        schema: dict[str, set[str]] = {}
        for table_name in table_names:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Did not recognize type .*", category=SAWarning)
                columns = inspector.get_columns(table_name)
            schema[table_name] = {column["name"] for column in columns}
        return schema
    finally:
        engine.dispose()


def _format_schema_gaps(missing_tables: list[str], missing_columns: dict[str, list[str]]) -> str:
    lines = [
        "database schema is not compatible with current application models.",
        "Run database migrations before starting workers, for example: python -m alembic upgrade head",
    ]
    if missing_tables:
        lines.append("missing tables:")
        lines.extend(f"  - {table_name}" for table_name in missing_tables)
    if missing_columns:
        lines.append("missing columns:")
        for table_name, columns in missing_columns.items():
            lines.append(f"  - {table_name}: {', '.join(columns)}")
    return "\n".join(lines)


def guard_database_schema(env: Mapping[str, str]) -> None:
    if not env_flag(env, "CROW_DB_ENABLED", True):
        return
    if not env_flag(env, "CROW_DB_SCHEMA_GUARD", True):
        return
    db_url = env_text(env, "CROW_DB_URL")
    if not db_url:
        return

    expected = _expected_database_schema()
    actual = _actual_database_schema(db_url)
    if not set(actual).intersection(expected):
        return
    missing_tables = sorted(table_name for table_name in expected if table_name not in actual)
    missing_columns = {
        table_name: sorted(columns - actual[table_name])
        for table_name, columns in sorted(expected.items())
        if table_name in actual and columns - actual[table_name]
    }
    if missing_tables or missing_columns:
        raise RuntimeError(_format_schema_gaps(missing_tables, missing_columns))


def run_startup_checks(env: Mapping[str, str]) -> None:
    guard_database_schema(env)


def main() -> int:
    try:
        run_startup_checks(os.environ)
    except Exception as exc:
        print(f"[docker-entrypoint] startup check failed: {exc}", file=sys.stderr, flush=True)
        return 1
    command = build_command(os.environ)
    print(f"[docker-entrypoint] exec: {' '.join(command)}", flush=True)
    return os.execvp(command[0], command)


if __name__ == "__main__":
    raise SystemExit(main())
