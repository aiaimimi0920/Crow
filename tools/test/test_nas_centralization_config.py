from __future__ import annotations

from pathlib import Path

from tools import docker_entrypoint


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_node_id_scopes_seed_worker_id_and_output_dir() -> None:
    command = docker_entrypoint.build_seed_collector_command(
        {
            "FAPAI_NODE_ID": "pc1",
            "FAPAI_OUTPUT_DIR": "/data/output/seed_collector_2",
            "FAPAI_SEED_WORKER_ID": "seed-2",
        }
    )

    assert command[command.index("--output-dir") + 1] == "/data/output/nodes/pc1/seed_collector_2"
    assert command[command.index("--worker-id") + 1] == "pc1-seed-2"


def test_node_id_scopes_detail_default_worker_id_and_output_dir() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_NODE_ID": "pc2",
            "FAPAI_OUTPUT_DIR": "/data/output/detail_worker",
            "FAPAI_RUN_MODE": "detail-worker",
        }
    )

    assert command[command.index("--output-dir") + 1] == "/data/output/nodes/pc2/detail_worker"
    assert command[command.index("--worker-id") + 1] == "pc2-detail-1"


def test_node_id_scoping_does_not_double_prefix_existing_values() -> None:
    command = docker_entrypoint.build_seed_collector_command(
        {
            "FAPAI_NODE_ID": "pc1",
            "FAPAI_OUTPUT_DIR": "/data/output/nodes/pc1/seed_collector",
            "FAPAI_SEED_WORKER_ID": "pc1-seed-1",
        }
    )

    assert command[command.index("--output-dir") + 1] == "/data/output/nodes/pc1/seed_collector"
    assert command[command.index("--worker-id") + 1] == "pc1-seed-1"


def test_nas_and_worker_compose_templates_exist_and_separate_roles() -> None:
    nas_compose = (REPO_ROOT / "docker-compose.nas-central.yml").read_text(encoding="utf-8")
    worker_compose = (REPO_ROOT / "docker-compose.worker-node.yml").read_text(encoding="utf-8")
    nas_env = (REPO_ROOT / "env.nas.example").read_text(encoding="utf-8")
    worker_env = (REPO_ROOT / "env.worker.example").read_text(encoding="utf-8")

    assert "fapaifang-postgres" in nas_compose
    assert "crow-api" in nas_compose
    assert "fapaifang-seed-collector" not in nas_compose
    assert "fapaifang-postgres" not in worker_compose
    assert "crow-api" not in worker_compose
    assert "FAPAI_NODE_ID" in worker_compose
    assert "FAPAI_LIST_BROWSER_FALLBACK" in worker_compose
    assert "FAPAI_DETAIL_CDP_ENDPOINT" in worker_env
    assert "FAPAI_SEED_CAPTCHA_SOLVER_ENABLED" in worker_env
    assert "FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED" in worker_env
    assert "FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED" in worker_env
    assert "FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED" in nas_compose
    assert "FAPAI_SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS" in nas_compose
    assert "FAPAI_NAS_AUTH_RECOVERY_ENABLED:-1" in nas_compose
    assert "FAPAI_NAS_AUTH_RECOVERY_STALL_SECONDS:-1800" in nas_compose
    assert "FAPAI_NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS:-300" in nas_compose
    assert "FAPAI_NAS_AUTH_RECOVERY_STATE_PATH: /data/datas/nas-auth-recovery.json" in nas_compose
    assert "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE: /data/secrets/nas-auth-recovery.token" in nas_compose
    assert "FAPAI_SEED_AUTH_PROBE_INTERVAL_SECONDS" in worker_compose
    assert "192.168.15.200:55432" in worker_env
    assert "192.168.15.200:8001" in worker_env
    assert "FAPAI_NAS_DATA_ROOT" in nas_env
    assert "FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED=0" in nas_env
    assert "FAPAI_SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS=180" in nas_env
    assert "FAPAI_NAS_AUTH_RECOVERY_ENABLED=1" in nas_env
    assert "FAPAI_NAS_AUTH_RECOVERY_STALL_SECONDS=1800" in nas_env
    assert "FAPAI_NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS=300" in nas_env


def test_nas_api_image_exposes_verifiable_build_identity_and_hotfix_dockerfile() -> None:
    compose = (REPO_ROOT / "docker-compose.nas-central.yml").read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    hotfix = (REPO_ROOT / "Dockerfile.nas-hotfix").read_text(encoding="utf-8")
    nas_env = (REPO_ROOT / "env.nas.example").read_text(encoding="utf-8")

    for name in (
        "FAPAI_BUILD_VERSION",
        "FAPAI_BUILD_COMMIT",
        "FAPAI_BUILD_TIME",
        "FAPAI_SOURCE_DIGEST",
    ):
        assert name in compose
        assert name in dockerfile
        assert name in hotfix
        assert name in nas_env
    assert "dockerfile: ${FAPAI_DOCKERFILE:-Dockerfile}" in compose
    assert "BASE_IMAGE: ${FAPAI_BASE_IMAGE:-fapaifang-collector:local}" in compose
    assert "org.opencontainers.image.revision" in compose
    assert "io.fapaifang.source-digest" in compose

    api_environment = compose.split("  crow-api:", 1)[1].split("    ports:", 1)[0]
    assert "FAPAI_COOKIE_SNAPSHOT_ROOT: ${FAPAI_COOKIE_SNAPSHOT_ROOT:-/data/shared}" in api_environment
    assert "FAPAI_COOKIE_SNAPSHOT_ROOT=/data/shared" in nas_env
    for name in (
        "FAPAI_BUILD_VERSION",
        "FAPAI_BUILD_COMMIT",
        "FAPAI_BUILD_TIME",
        "FAPAI_SOURCE_DIGEST",
    ):
        assert f"{name}: ${{{name}:-" in api_environment


def test_nas_api_deploy_helper_requires_backup_identity_health_gate_and_rollback() -> None:
    script = (REPO_ROOT / "scripts" / "deploy-nas-central-api.sh").read_text(encoding="utf-8")

    assert "set -euo pipefail" in script
    assert "pg_dump" in script
    assert "pg_restore -l" in script
    assert "docker image tag" in script
    assert "CROW_BUILD_VERSION" in script
    assert "CROW_SOURCE_DIGEST" in script
    assert 'build.get("version")' in script
    assert 'build.get("source_digest")' in script
    assert "up -d --no-deps --no-build crow-api" in script
    assert "Candidate container state before rollback" in script
    assert "docker logs --tail 200 --timestamps" in script
    assert "/api/collection/overview" in script
    assert "--dry-run" in script
    assert "shared_auth_recovery_token_file" in script
    assert "CROW_SHARED_ARTIFACT_ROOT" in script
    assert "os.replace(temporary, target)" in script
    assert 'chown --reference="$(dirname "$shared_auth_recovery_token_file")"' in script
    assert "--auth-recovery-hotfix" in script
    assert 'crow_set_env CROW_DOCKERFILE "Dockerfile.nas-auth-recovery"' in script
    assert 'crow_set_env CROW_NAS_ENV_FILE "${CROW_NAS_ENV_FILE:-$env_file}"' in script
    assert 'com.docker.compose.project' in script
    assert 'crow_set_env CROW_IMAGE "$candidate_image"' in script
    assert '--project-name "$compose_project"' in script
    assert "Candidate image build failed; the running API was not replaced." in script


def test_nas_api_deploy_health_gate_follows_tls_config_and_public_status() -> None:
    script = (REPO_ROOT / "scripts" / "deploy-nas-central-api.sh").read_text(encoding="utf-8")
    nas_env = (REPO_ROOT / "env.nas.example").read_text(encoding="utf-8")

    assert "FAPAI_API_TLS_CERT_FILE=" in nas_env
    assert "FAPAI_API_TLS_KEY_FILE=" in nas_env
    assert "FAPAI_API_HOST_BIND_ADDRESS=127.0.0.1" in nas_env
    assert "FAPAI_API_HEALTH_HOST=localhost" in nas_env
    assert "api_health_scheme=https" in script
    assert 'api_health_curl_args=(--resolve "${api_health_host}:${api_port}:${api_health_resolve_address}")' in script
    assert 'api_health_curl_args+=(--cacert "$api_health_ca_file")' in script
    assert 'health_url="${api_health_scheme}://${api_health_host}:${api_port}/api/status"' in script
    assert 'curl -fsS --max-time 5 "${api_health_curl_args[@]}" "$health_url"' in script
    assert 'if not (payload.get("auth_recovery") or {}).get("enabled"):' in script


def test_nas_api_defaults_to_loopback_and_guards_external_binding_with_tls() -> None:
    compose = (REPO_ROOT / "docker-compose.nas-central.yml").read_text(encoding="utf-8")
    script = (REPO_ROOT / "scripts" / "deploy-nas-central-api.sh").read_text(encoding="utf-8")
    runbook = (REPO_ROOT / "docs" / "nas-central-deployment.md").read_text(encoding="utf-8")

    assert '"${FAPAI_API_HOST_BIND_ADDRESS:-127.0.0.1}:${FAPAI_API_HOST_PORT:-9520}:8001"' in compose
    assert 'api_host_bind_address="${CROW_API_HOST_BIND_ADDRESS:-127.0.0.1}"' in script
    assert 'if [[ "$api_bind_is_loopback" != 1 && -z "$api_tls_cert_file" ]]; then' in script
    assert "External NAS API binding requires a configured TLS certificate and key." in script
    assert "FAPAI_API_HOST_BIND_ADDRESS` 设为 NAS 的 IPv4 地址或 `0.0.0.0`" in runbook
    assert '"${api_scheme}://${api_health_host}:${FAPAI_API_HOST_PORT:-9520}/api/status"' in runbook
    assert "curl -s http://127.0.0.1:8001/api/status" not in runbook


def test_nas_auth_recovery_hotfix_only_overlays_recovery_server_files() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile.nas-auth-recovery").read_text(encoding="utf-8")

    copy_lines = [line.strip() for line in dockerfile.splitlines() if line.startswith("COPY ")]
    assert copy_lines == [
        "COPY src/server.py /app/src/server.py",
        "COPY src/nas_auth_recovery.py /app/src/nas_auth_recovery.py",
    ]


def test_detail_worker_command_passes_durable_archive_root() -> None:
    command = docker_entrypoint.build_detail_worker_command(
        {
            "FAPAI_NODE_ID": "pc2",
            "FAPAI_DETAIL_ARCHIVE_ROOT": "/data/datas",
        }
    )

    assert command[command.index("--detail-archive-root") + 1] == "/data/datas"


def test_detail_worker_command_omits_archive_root_when_unset() -> None:
    command = docker_entrypoint.build_detail_worker_command({"FAPAI_NODE_ID": "pc2"})

    assert "--detail-archive-root" not in command


def test_worker_node_compose_defaults_archive_root_to_mounted_datas() -> None:
    """容器里 /data/datas 是必挂的 bind，默认打开归档避免这一步被忘掉。

    代码层保持 opt-in（不配就不归档），但 worker 容器里挂载一定存在，
    所以在 compose 里给默认值。否则漏配一个环境变量就会让持久归档静默失效，
    而这正是 228,959 行没有归档原料的成因。
    """
    compose = (REPO_ROOT / "docker-compose.worker-node.yml").read_text(encoding="utf-8")

    assert "${FAPAI_DETAIL_ARCHIVE_ROOT:-/data/datas}" in compose

    detail_env_block = compose.split("x-worker-node-detail-env:")[1].split("x-worker-node-volumes:")[0]
    assert "FAPAI_DETAIL_ARCHIVE_ROOT" in detail_env_block, "归档变量必须在 detail env 块里"


def test_worker_nodes_prefer_live_cdp_cookies_before_snapshot_fallback() -> None:
    worker_compose = (REPO_ROOT / "docker-compose.worker-node.yml").read_text(encoding="utf-8")
    worker_env = (REPO_ROOT / "env.worker.example").read_text(encoding="utf-8")

    assert "FAPAI_COOKIE_SNAPSHOT_PREFER: ${FAPAI_COOKIE_SNAPSHOT_PREFER:-0}" in worker_compose
    assert "FAPAI_COOKIE_SNAPSHOT_PREFER=0" in worker_env


def test_worker_nodes_expose_report_cdp_endpoint_for_central_solver_callbacks() -> None:
    worker_compose = (REPO_ROOT / "docker-compose.worker-node.yml").read_text(encoding="utf-8")
    worker_env = (REPO_ROOT / "env.worker.example").read_text(encoding="utf-8")

    assert "FAPAI_REPORT_CDP_ENDPOINT: ${FAPAI_REPORT_CDP_ENDPOINT:-}" in worker_compose
    assert "FAPAI_REPORT_CDP_ENDPOINT=" in worker_env


def test_worker_node_compose_enables_real_solver_integration_for_seed_and_detail_paths() -> None:
    compose = (REPO_ROOT / "docker-compose.worker-node.yml").read_text(encoding="utf-8")

    assert "${FAPAI_DETAIL_CDP_ENDPOINT:-http://host.docker.internal:9223}" in compose
    assert "${FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED:-1}" in compose
    assert "${FAPAI_DETAIL_BROWSER_FALLBACK:-1}" in compose
    assert "${FAPAI_SEED_CAPTCHA_SOLVER_ENABLED:-1}" not in compose
    assert "${FAPAI_SEED_CAPTCHA_SOLVER_ENABLED:-0}" not in compose


def test_nas_deployment_doc_requires_seed_and_detail_solver_flags_for_real_module_integration() -> None:
    runbook = (REPO_ROOT / "docs" / "nas-central-deployment.md").read_text(encoding="utf-8")

    assert "FAPAI_SEED_CAPTCHA_SOLVER_ENABLED=1" in runbook
    assert "FAPAI_DETAIL_CDP_ENDPOINT=http://host.docker.internal:9223" in runbook
    assert "FAPAI_DETAIL_BROWSER_FALLBACK=1" in runbook
    assert "FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED=1" in runbook


def test_dockerfile_builds_and_copies_collector_desktop_dist_for_html_console() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "AS collector_desktop_builder" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "COPY --from=collector_desktop_builder" in dockerfile
    assert "/app/collector-desktop/dist" in dockerfile
    assert "!collector-desktop/index.html" in dockerignore
