from __future__ import annotations

import subprocess
import sys
import warnings

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SAWarning

from src.storage.models import Base
from tools import docker_entrypoint


def test_dockerfile_supports_offline_wheelhouse_installation() -> None:
    dockerfile = docker_entrypoint.REPO_ROOT.joinpath("Dockerfile").read_text(encoding="utf-8")

    assert "ARG PYTHON_BASE_IMAGE=python:3.12-slim" in dockerfile
    assert "COPY vendor/wheels/ /tmp/wheels/" in dockerfile
    assert "--no-index --find-links=/tmp/wheels" in dockerfile


def test_importing_docker_entrypoint_does_not_eagerly_import_storage_repository() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import tools.docker_entrypoint; print('src.storage.repository' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == "False"


def test_default_compose_uses_docker_volumes_for_verified_persistent_state() -> None:
    compose = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")
    postgres_compose = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.postgres.yml").read_text(encoding="utf-8")

    assert "fapaifang-output:/data/output" in compose
    assert "fapaifang-datas:/data/datas" in compose
    assert "fapaifang-jobs:/data/jobs" in compose
    assert "fapaifang-secrets:/data/secrets" in compose
    assert "volumes:\n  fapaifang-output:\n  fapaifang-datas:\n  fapaifang-jobs:\n  fapaifang-secrets:" in compose
    assert "postgres_data:/var/lib/postgresql/data" in postgres_compose
    assert "volumes:\n  postgres_data:" in postgres_compose


def test_collection_and_worker_node_compose_wire_worker_ca_and_token() -> None:
    collection = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")
    worker_node = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.worker-node.yml").read_text(encoding="utf-8")
    for compose in (collection, worker_node):
        assert "FAPAI_API_CA_FILE: ${FAPAI_API_CA_FILE:-}" in compose
        assert "FAPAI_COLLECTION_WORKER_TOKEN_FILE: ${FAPAI_COLLECTION_WORKER_TOKEN_FILE:-/data/secrets/collection-worker.token}" in compose
    assert "FAPAI_API_BASE_URL: ${FAPAI_CENTRAL_API_BASE_URL:?set FAPAI_CENTRAL_API_BASE_URL}" in worker_node
    assert "http://192.168.15.200:8001/api" not in worker_node


def test_host_bind_overrides_are_explicit_opt_in() -> None:
    collection_override = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.host-bind.yml").read_text(encoding="utf-8")
    postgres_override = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.postgres.host-bind.yml").read_text(encoding="utf-8")

    assert "source: ${FAPAI_DATA_ROOT_HOST:?set FAPAI_DATA_ROOT_HOST}/output" in collection_override
    assert "target: /data/output" in collection_override
    assert "source: ${FAPAI_DATA_ROOT_HOST:?set FAPAI_DATA_ROOT_HOST}/datas" in collection_override
    assert "target: /data/datas" in collection_override
    assert "source: ${FAPAI_DATA_ROOT_HOST:?set FAPAI_DATA_ROOT_HOST}/jobs" in collection_override
    assert "target: /data/jobs" in collection_override
    assert "source: ${FAPAI_DATA_ROOT_HOST:?set FAPAI_DATA_ROOT_HOST}/secrets" in collection_override
    assert "target: /data/secrets" in collection_override
    assert "read_only: true" in collection_override
    assert "source: ${FAPAI_DATA_ROOT_HOST:?set FAPAI_DATA_ROOT_HOST}/postgres" in postgres_override
    assert "target: /var/lib/postgresql/data" in postgres_override


def test_host_bind_api_can_refresh_cookie_snapshot_used_by_workers() -> None:
    collection_override = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.host-bind.yml").read_text(encoding="utf-8")
    api_block = collection_override[
        collection_override.index("  crow-api:"):
        collection_override.index("  fapaifang-area-followup:")
    ]

    assert "source: ${FAPAI_DATA_ROOT_HOST:?set FAPAI_DATA_ROOT_HOST}/secrets" in api_block
    assert "target: /data/secrets" in api_block
    assert "read_only: true" not in api_block


def test_compose_uses_ignored_local_env_file() -> None:
    compose = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")
    gitignore = docker_entrypoint.REPO_ROOT.joinpath(".gitignore").read_text(encoding="utf-8")
    dockerignore = docker_entrypoint.REPO_ROOT.joinpath(".dockerignore").read_text(encoding="utf-8")

    assert "env_file:" in compose
    assert "path: docker.local.env" in compose
    assert "required: false" in compose
    assert "docker.local.env" in gitignore
    assert "docker.local.env" in dockerignore


def test_compose_defaults_to_split_seed_and_detail_workers() -> None:
    compose = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")

    assert "fapaifang-seed-collector:" in compose
    assert "container_name: fapaifang-seed-collector" in compose
    assert "FAPAI_RUN_MODE: seed-collector" in compose
    assert "FAPAI_API_BASE_URL: ${FAPAI_API_BASE_URL:-http://crow-api:8001/api}" in compose
    assert "fapaifang-detail-worker:" in compose
    assert "container_name: fapaifang-detail-worker" in compose
    assert "FAPAI_RUN_MODE: detail-worker" in compose
    assert compose.count("FAPAI_API_BASE_URL: ${FAPAI_API_BASE_URL:-http://crow-api:8001/api}") >= 2
    assert 'profiles: ["legacy"]' in compose


def test_compose_defines_separate_detail_analysis_worker() -> None:
    compose = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")

    assert "fapaifang-detail-analysis-worker:" in compose
    assert "container_name: fapaifang-detail-analysis-worker" in compose
    assert "FAPAI_RUN_MODE: detail-analysis-worker" in compose
    assert "FAPAI_OUTPUT_DIR: /data/output/detail_worker" in compose
    assert "FAPAI_DETAIL_RAW_ONLY: \"0\"" in compose


def test_api_service_disables_runtime_db_ddl_like_workers() -> None:
    compose = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")

    assert "crow-api:" in compose
    assert "FAPAI_DB_SCHEMA_GUARD: ${FAPAI_API_DB_SCHEMA_GUARD:-0}" in compose
    assert "FAPAI_DB_AUTO_CREATE: ${FAPAI_API_DB_AUTO_CREATE:-0}" in compose
    assert "FAPAI_DB_ENABLE_POSTGIS: ${FAPAI_API_DB_ENABLE_POSTGIS:-0}" in compose


def test_nas_central_compose_pins_builder_base_images_to_dockerfile_digests() -> None:
    dockerfile = docker_entrypoint.REPO_ROOT.joinpath("Dockerfile").read_text(encoding="utf-8")
    compose = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.nas-central.yml").read_text(encoding="utf-8")
    for line in (
        "ARG PYTHON_BASE_IMAGE=python:3.12-slim@sha256:a0e2dd78cc679ddfffea960fe45ecfcff9ac2f68d67917a0edfcde5c2100151b",
        "ARG NODE_BASE_IMAGE=node:22-alpine@sha256:b6f26b36c8ff49624cfdac716b8ea1138d606df02586a77d364bb5536a634f85",
    ):
        image_name, digest = line.removeprefix("ARG ").split("=", 1)
        assert line in dockerfile
        assert f"{image_name}: ${{{image_name}:-{digest}}}" in compose


def test_api_compose_exposes_optional_tls_material_without_enabling_it_by_default() -> None:
    collection = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")
    nas = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.nas-central.yml").read_text(encoding="utf-8")
    for compose in (collection, nas):
        assert "FAPAI_API_TLS_CERT_FILE: ${FAPAI_API_TLS_CERT_FILE:-}" in compose
        assert "FAPAI_API_TLS_KEY_FILE: ${FAPAI_API_TLS_KEY_FILE:-}" in compose
    assert "FAPAI_API_TLS_CERT_FILE: ${FAPAI_API_TLS_CERT_FILE:-}" in collection
    api_block = collection[collection.index("  crow-api:"):collection.index("  fapaifang-area-followup:")]
    assert "target: /data/secrets" not in api_block
    assert "FAPAI_API_TLS_CERT_FILE: ${FAPAI_API_TLS_CERT_FILE:-}" in api_block


def test_api_services_receive_distinct_role_credential_paths() -> None:
    collection = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")
    nas = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.nas-central.yml").read_text(encoding="utf-8")

    expected = (
        "FAPAI_COLLECTION_WORKER_TOKEN_FILE: ${FAPAI_COLLECTION_WORKER_TOKEN_FILE:-/data/secrets/collection-worker.token}",
        "FAPAI_ENGINE_OPERATOR_TOKEN_FILE: ${FAPAI_ENGINE_OPERATOR_TOKEN_FILE:-/data/secrets/engine-operator.token}",
        "FAPAI_ENGINE_AGENT_TOKEN_FILE: ${FAPAI_ENGINE_AGENT_TOKEN_FILE:-/data/secrets/engine-agent.token}",
    )
    for compose in (collection, nas):
        api_block = compose[compose.index("  crow-api:"):]
        for line in expected:
            assert line in api_block
        if compose is collection:
            assert "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE:" not in api_block


def test_collection_workers_receive_optional_ca_and_worker_credential_paths() -> None:
    compose = docker_entrypoint.REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")
    worker_services = compose[:compose.index("  crow-api:")]
    worker_count = worker_services.count("FAPAI_API_BASE_URL: ${FAPAI_API_BASE_URL:-http://crow-api:8001/api}")
    assert worker_count == 12
    assert worker_services.count("FAPAI_API_CA_FILE: ${FAPAI_API_CA_FILE:-}") == worker_count
    assert worker_services.count("FAPAI_COLLECTION_WORKER_TOKEN_FILE: ${FAPAI_COLLECTION_WORKER_TOKEN_FILE:-/data/secrets/collection-worker.token}") == worker_count


def test_live_loop_command_uses_persistent_resume_state() -> None:
    command = docker_entrypoint.build_live_command(
        {
            "FAPAI_RUN_MODE": "live-loop",
            "FAPAI_OUTPUT_DIR": "/data/live",
            "FAPAI_RESUME_STATE": "/data/live/resume_state.json",
            "FAPAI_CDP_ENDPOINT": "http://host.docker.internal:9223",
            "FAPAI_TARGET_URL": "https://sf.taobao.com/list/page",
            "FAPAI_TARGET_SUCCESS": "3",
            "FAPAI_MAX_ATTEMPTS": "20",
            "FAPAI_LOOP_INTERVAL_SECONDS": "0",
            "FAPAI_MAX_RUNS": "2",
        }
    )

    assert command[:3] == [sys.executable, "tools/live_batch_smoke.py", "--output-dir"]
    assert "/data/live" in command
    assert "--loop" in command
    assert command[command.index("--resume-state") + 1] == "/data/live/resume_state.json"
    assert command[command.index("--cdp-endpoint") + 1] == "http://host.docker.internal:9223"
    assert command[command.index("--target-success") + 1] == "3"
    assert command[command.index("--max-attempts") + 1] == "20"
    assert command[command.index("--max-runs") + 1] == "2"
    assert command[command.index("--list-st-params") + 1] == "2,1,0,3,4,5"
    assert command[command.index("--list-max-pages") + 1] == "83"
    assert "--llm-preflight" in command


def test_live_command_passes_multi_sort_union_options() -> None:
    command = docker_entrypoint.build_live_command(
        {
            "FAPAI_RUN_MODE": "live-batch",
            "FAPAI_LIST_ST_PARAMS": "2,1",
            "FAPAI_LIST_LOCATION_CODES": "110101,110102",
            "FAPAI_LIST_CATEGORIES": "50025969",
            "FAPAI_LIST_MAX_PAGES": "5",
            "FAPAI_LIST_STOP_ON_EMPTY": "0",
        }
    )

    assert command[command.index("--list-st-params") + 1] == "2,1"
    assert command[command.index("--list-location-codes") + 1] == "110101,110102"
    assert command[command.index("--list-categories") + 1] == "50025969"
    assert command[command.index("--list-max-pages") + 1] == "5"
    assert "--no-list-stop-on-empty" in command


def test_live_command_can_disable_llm_preflight() -> None:
    command = docker_entrypoint.build_live_command(
        {
            "FAPAI_RUN_MODE": "live-batch",
            "FAPAI_LLM_PREFLIGHT": "0",
        }
    )

    assert "--llm-preflight" not in command


def test_seed_collector_command_uses_db_backed_region_sort_progress() -> None:
    command = docker_entrypoint.build_seed_collector_command(
        {
            "FAPAI_OUTPUT_DIR": "/data/output/seed_collector",
            "FAPAI_CDP_ENDPOINT": "http://host.docker.internal:9223",
            "FAPAI_SEED_JOB_KEY": "guangdong-guangzhou-nansha-50025969",
            "FAPAI_SEED_PROVINCE": "广东省",
            "FAPAI_SEED_CITY": "广州市",
            "FAPAI_SEED_DISTRICT": "南沙区",
            "FAPAI_SEED_LOCATION_CODE": "440115",
            "FAPAI_SEED_CATEGORY": "50025969",
            "FAPAI_SEED_SORTS": "bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远",
            "FAPAI_SEED_MAX_PAGE": "83",
            "FAPAI_SEED_PAGES_PER_RUN": "7",
            "FAPAI_SEED_LOOP_INTERVAL_SECONDS": "1800",
            "FAPAI_SEED_ACTIVE_LOOP_INTERVAL_SECONDS": "0",
            "FAPAI_SEED_MAX_RUNS": "2",
        }
    )

    assert command[:2] == [sys.executable, "tools/seed_collector.py"]
    assert command[command.index("--output-dir") + 1] == "/data/output/seed_collector"
    assert command[command.index("--job-key") + 1] == "guangdong-guangzhou-nansha-50025969"
    assert command[command.index("--location-code") + 1] == "440115"
    assert command[command.index("--sorts") + 1] == "bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远"
    assert command[command.index("--max-page") + 1] == "83"
    assert command[command.index("--pages-per-run") + 1] == "7"
    assert "--loop" in command
    assert command[command.index("--active-loop-interval-seconds") + 1] == "0"
    assert command[command.index("--max-runs") + 1] == "2"


def test_seed_collector_command_passes_captcha_solver_enabled_flag() -> None:
    command = docker_entrypoint.build_seed_collector_command(
        {
            "FAPAI_CAPTCHA_SOLVER_ENABLED": "1",
            "FAPAI_API_BASE_URL": "http://collection-api:8001/api",
        }
    )

    assert "--solver-enabled" in command
    assert command[command.index("--api-base-url") + 1] == "http://collection-api:8001/api"


def test_seed_collector_command_honors_seed_specific_solver_env_flag() -> None:
    command = docker_entrypoint.build_seed_collector_command(
        {
            "FAPAI_SEED_CAPTCHA_SOLVER_ENABLED": "1",
        }
    )

    assert "--solver-enabled" in command


def test_seed_collector_command_passes_jobs_file_and_parallel_sorts_for_seed_pool() -> None:
    command = docker_entrypoint.build_seed_collector_command(
        {
            "FAPAI_SEED_JOBS_FILE": "/data/jobs/seed_jobs_all.json",
            "FAPAI_SEED_PARALLEL_SORTS": "1",
        }
    )

    assert command[command.index("--jobs-file") + 1] == "/data/jobs/seed_jobs_all.json"
    assert "--parallel-sorts" in command


def test_seed_collector_command_passes_failure_cooldown() -> None:
    command = docker_entrypoint.build_seed_collector_command(
        {
            "FAPAI_SEED_FAILURE_COOLDOWN_THRESHOLD": "10",
            "FAPAI_SEED_FAILURE_COOLDOWN_SECONDS": "120",
        }
    )

    assert command[command.index("--failure-cooldown-threshold") + 1] == "10"
    assert command[command.index("--failure-cooldown-seconds") + 1] == "120"


def test_detail_worker_command_consumes_db_seed_queue() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_OUTPUT_DIR": "/data/output/detail_worker",
            "FAPAI_CDP_ENDPOINT": "http://host.docker.internal:9223",
            "FAPAI_DETAIL_TARGET_SUCCESS": "3",
            "FAPAI_DETAIL_MAX_ATTEMPTS": "10",
            "FAPAI_DETAIL_ITEM_MAX_ATTEMPTS": "4",
            "FAPAI_DETAIL_LOOP_INTERVAL_SECONDS": "900",
            "FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS": "0",
            "FAPAI_DETAIL_MAX_RUNS": "2",
            "FAPAI_ENABLE_RISK": "1",
            "FAPAI_LLM_PREFLIGHT": "1",
        }
    )

    assert command[:2] == [sys.executable, "tools/detail_worker.py"]
    assert command[command.index("--output-dir") + 1] == "/data/output/detail_worker"
    assert command[command.index("--target-success") + 1] == "3"
    assert command[command.index("--max-attempts") + 1] == "10"
    assert command[command.index("--item-max-attempts") + 1] == "4"
    assert "--risk" in command
    assert "--llm-preflight" in command
    assert "--loop" in command
    assert command[command.index("--active-loop-interval-seconds") + 1] == "0"
    assert command[command.index("--max-runs") + 1] == "2"


def test_detail_worker_command_can_enable_raw_only_capture() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_OUTPUT_DIR": "/data/output/detail_worker",
            "FAPAI_DETAIL_RAW_ONLY": "1",
        }
    )

    assert "--raw-only" in command


def test_detail_analysis_worker_command_consumes_raw_artifacts_with_llm_preflight() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_RUN_MODE": "detail-analysis-worker",
            "FAPAI_OUTPUT_DIR": "/data/output/detail_worker",
            "FAPAI_DETAIL_RAW_ONLY": "1",
            "FAPAI_LLM_PREFLIGHT": "1",
        }
    )

    assert "--analysis-only" in command
    assert "--raw-only" not in command
    assert "--llm-preflight" in command
    assert "--loop" in command


def test_detail_analysis_worker_command_uses_analysis_specific_throughput_env() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_RUN_MODE": "detail-analysis-worker",
            "FAPAI_DETAIL_ANALYSIS_TARGET_SUCCESS": "7",
            "FAPAI_DETAIL_ANALYSIS_MAX_ATTEMPTS": "9",
            "FAPAI_DETAIL_ANALYSIS_ITEM_MAX_ATTEMPTS": "2",
            "FAPAI_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS": "30",
            "FAPAI_DETAIL_ANALYSIS_ACTIVE_LOOP_INTERVAL_SECONDS": "2",
        }
    )

    assert command[command.index("--target-success") + 1] == "7"
    assert command[command.index("--max-attempts") + 1] == "9"
    assert command[command.index("--item-max-attempts") + 1] == "2"
    assert command[command.index("--loop-interval-seconds") + 1] == "30"
    assert command[command.index("--active-loop-interval-seconds") + 1] == "2"


def test_detail_analysis_worker_command_inherits_detail_active_loop_interval() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_RUN_MODE": "detail-analysis-worker",
            "FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS": "0",
            "FAPAI_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS": "30",
        }
    )

    assert command[command.index("--loop-interval-seconds") + 1] == "30"
    assert command[command.index("--active-loop-interval-seconds") + 1] == "0"


def test_detail_worker_command_passes_failure_cooldown() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_DETAIL_FAILURE_COOLDOWN_SECONDS": "1800",
        }
    )

    assert command[command.index("--failure-cooldown-seconds") + 1] == "1800"


def test_detail_worker_command_passes_api_base_url_and_solver_flag() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_API_BASE_URL": "http://collection-api:8001/api",
            "FAPAI_CAPTCHA_SOLVER_ENABLED": "1",
        }
    )

    assert command[command.index("--api-base-url") + 1] == "http://collection-api:8001/api"
    assert "--solver-enabled" in command


def test_detail_worker_command_honors_detail_specific_cdp_and_solver_env_flags() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_DETAIL_CDP_ENDPOINT": "http://host.docker.internal:9555",
            "FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED": "1",
        }
    )

    assert command[command.index("--cdp-endpoint") + 1] == "http://host.docker.internal:9555"
    assert "--solver-enabled" in command


def test_live_batch_command_can_disable_resume_explicitly() -> None:
    command = docker_entrypoint.build_live_command(
        {
            "FAPAI_RUN_MODE": "live-batch",
            "FAPAI_DISABLE_RESUME": "1",
        }
    )

    assert "--loop" not in command
    assert "--no-resume" in command
    assert "--resume-state" not in command


def test_api_command_passes_db_url_and_location_codes() -> None:
    command = docker_entrypoint.build_api_command(
        {
            "FAPAI_API_PORT": "8011",
            "FAPAI_DB_URL": "postgresql+psycopg://user:pass@postgres:5432/fapaifang",
            "FAPAI_SEED_LOCATION_CODES": "110101,110102",
        }
    )

    assert command[:2] == [sys.executable, "tools/run_isolated_collection_api.py"]
    assert command[command.index("--port") + 1] == "8011"
    assert command[command.index("--db-url") + 1] == "postgresql+psycopg://user:pass@postgres:5432/fapaifang"
    assert command.count("--seed-location-code") == 2
    assert "110101" in command
    assert "110102" in command


def test_area_followup_command_supports_apply_and_push() -> None:
    command = docker_entrypoint.build_area_followup_command(
        {
            "FAPAI_AREA_QUEUE": "/data/live/area_followup_queue.json",
            "FAPAI_OUTPUT_DIR": "/data/live",
            "FAPAI_CDP_ENDPOINT": "http://host.docker.internal:9223",
            "FAPAI_AREA_APPLY_PATCHES": "true",
            "FAPAI_AREA_PUSH_URL": "http://crow-api:8001/api/collection/details/area_result",
        }
    )

    assert command[:2] == [sys.executable, "tools/area_followup_runner.py"]
    assert command[command.index("--queue") + 1] == "/data/live/area_followup_queue.json"
    assert command[command.index("--output-dir") + 1] == "/data/live"
    assert "--apply-patches" in command
    assert command[command.index("--push-area-result") + 1] == "http://crow-api:8001/api/collection/details/area_result"


def test_database_schema_guard_fails_fast_when_existing_table_is_missing_required_column(tmp_path) -> None:
    db_path = tmp_path / "old-schema.sqlite3"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE fapai_seed_item (
                    item_id VARCHAR(64) PRIMARY KEY,
                    source_item_id VARCHAR(64)
                )
                """
            )
        )

    with pytest.raises(RuntimeError) as exc_info:
        docker_entrypoint.guard_database_schema(
            {
                "FAPAI_DB_URL": f"sqlite:///{db_path.as_posix()}",
                "FAPAI_DB_ENABLED": "1",
                "FAPAI_DB_SCHEMA_GUARD": "1",
            }
        )

    message = str(exc_info.value)
    assert "database schema is not compatible" in message
    assert "fapai_seed_item" in message
    assert "detail_completed_at" in message


def test_actual_database_schema_suppresses_irrelevant_sqlalchemy_type_warnings(monkeypatch) -> None:
    class _FakeEngine:
        def __init__(self) -> None:
            self.disposed = False

        def dispose(self) -> None:
            self.disposed = True

    class _FakeInspector:
        def get_table_names(self):
            return ["property_listing"]

        def get_columns(self, _table_name):
            warnings.warn("Did not recognize type 'geography' of column 'geom'", SAWarning)
            return [{"name": "item_id"}, {"name": "geom"}]

    fake_engine = _FakeEngine()
    monkeypatch.setattr(docker_entrypoint, "create_engine", lambda *_args, **_kwargs: fake_engine)
    monkeypatch.setattr(docker_entrypoint, "inspect", lambda _engine: _FakeInspector())

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        actual = docker_entrypoint._actual_database_schema("postgresql+psycopg://example")

    assert actual == {"property_listing": {"item_id", "geom"}}
    assert fake_engine.disposed is True
    assert caught == []


def test_database_schema_guard_passes_for_current_model_schema(tmp_path) -> None:
    db_path = tmp_path / "current-schema.sqlite3"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    Base.metadata.create_all(engine)

    docker_entrypoint.guard_database_schema(
        {
            "FAPAI_DB_URL": f"sqlite:///{db_path.as_posix()}",
            "FAPAI_DB_ENABLED": "1",
            "FAPAI_DB_SCHEMA_GUARD": "1",
        }
    )


def test_database_schema_guard_allows_empty_database_for_repository_auto_create(tmp_path) -> None:
    db_path = tmp_path / "empty-schema.sqlite3"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    with engine.begin():
        pass

    docker_entrypoint.guard_database_schema(
        {
            "FAPAI_DB_URL": f"sqlite:///{db_path.as_posix()}",
            "FAPAI_DB_ENABLED": "1",
            "FAPAI_DB_SCHEMA_GUARD": "1",
        }
    )


def test_database_schema_guard_skips_when_database_url_is_absent() -> None:
    docker_entrypoint.guard_database_schema(
        {
            "FAPAI_DB_ENABLED": "1",
            "FAPAI_DB_SCHEMA_GUARD": "1",
        }
    )


def test_database_schema_guard_skips_when_explicitly_disabled(tmp_path) -> None:
    db_path = tmp_path / "old-schema.sqlite3"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE fapai_seed_item (item_id VARCHAR(64) PRIMARY KEY)"))

    docker_entrypoint.guard_database_schema(
        {
            "FAPAI_DB_URL": f"sqlite:///{db_path.as_posix()}",
            "FAPAI_DB_ENABLED": "1",
            "FAPAI_DB_SCHEMA_GUARD": "0",
        }
    )


def test_main_returns_nonzero_and_does_not_exec_when_startup_check_fails(monkeypatch, capsys) -> None:
    executed_commands: list[list[str]] = []

    def _fail_startup_checks(_env):
        raise RuntimeError("schema drift detected")

    def _record_subprocess_call(command):
        executed_commands.append(command)
        return 0

    monkeypatch.setattr(docker_entrypoint, "run_startup_checks", _fail_startup_checks)
    monkeypatch.setattr(docker_entrypoint.subprocess, "call", _record_subprocess_call)

    assert docker_entrypoint.main() == 1
    assert executed_commands == []
    captured = capsys.readouterr()
    assert "[docker-entrypoint] startup check failed:" in captured.err
    assert "schema drift detected" in captured.err
