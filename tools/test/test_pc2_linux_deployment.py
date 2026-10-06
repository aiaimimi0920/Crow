from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import pc2_linux_healthcheck

REPO_ROOT = Path(__file__).resolve().parents[2]
OPS_ROOT = REPO_ROOT / "ops" / "pc2-linux"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["Dockerfile.browser", "Dockerfile.auth-recovery"])
def test_browser_overlay_ships_all_solver_owners(name: str) -> None:
    from tools import pc2_local_solver

    dockerfile = _read(OPS_ROOT / name)
    assert "COPY tools/pc2_solver_*.py /app/tools/" in dockerfile.splitlines()
    copied_modules = {
        f"tools.{path.stem}" for path in (REPO_ROOT / "tools").glob("pc2_solver_*.py")
    }
    assert set(pc2_local_solver._IMPLEMENTATION_MODULES) <= copied_modules
    assert "tools.pc2_solver_config" in copied_modules


def test_linux_compose_has_expected_decoupled_topology() -> None:
    compose = _read(OPS_ROOT / "compose.yaml")

    expected_services = (
        "pc2-browser-solver",
        "pc2-seed-1",
        "pc2-detail-1",
        "pc2-detail-2",
        "pc2-detail-3",
        "pc2-analysis-1",
        "pc2-analysis-2",
        "pc2-analysis-3",
        "pc2-analysis-4",
    )
    for service in expected_services:
        assert f"  {service}:" in compose
    analysis_section = compose.split("  pc2-analysis-1:", 1)[1]
    assert "condition: service_healthy" not in analysis_section
    assert 'FAPAI_DETAIL_ANALYSIS_ONLY: "1"' in analysis_section
    assert "deepseek" not in compose.lower(), (
        "model secrets and routing belong in runtime.env"
    )
    assert "FAPAI_API_CA_FILE: ${FAPAI_API_CA_FILE:-}" in compose
    assert (
        "FAPAI_API_BASE_URL: ${FAPAI_CENTRAL_API_BASE_URL:?set FAPAI_CENTRAL_API_BASE_URL}"
        in compose
    )
    assert "http://192.168.15.200:8001/api" not in compose
    assert (
        "FAPAI_COLLECTION_WORKER_TOKEN_FILE: ${FAPAI_COLLECTION_WORKER_TOKEN_FILE:-/data/secrets/collection-worker.token}"
        in compose
    )
    assert "target: /data/secrets" in compose


def test_linux_compose_preserves_solver_retry_contract() -> None:
    compose = _read(OPS_ROOT / "compose.yaml")
    env_example = _read(OPS_ROOT / "env.example")

    assert "FAPAI_SOLVER_COOLDOWN_FAIL_THRESHOLD:-10" in compose
    assert "FAPAI_SOLVER_COOLDOWN_SECONDS:-180" in compose
    assert "FAPAI_SLIDER_RETRY_INTERVAL_SECONDS:-5" in compose
    assert 'FAPAI_SOLVER_MANUAL_FALLBACK_ENABLED: "0"' in compose
    assert 'FAPAI_SOLVER_ENABLE_HEADED_PLAYWRIGHT: "0"' in compose
    assert "FAPAI_LOCAL_SOLVER_EXECUTION_TIMEOUT_SECONDS:-180" in compose
    assert "FAPAI_LOCAL_SOLVER_TERMINATE_GRACE_SECONDS:-5" in compose
    assert "FAPAI_LOCAL_SOLVER_WATCHDOG_STALE_SECONDS:-300" in compose
    assert "FAPAI_LOCAL_SOLVER_WATCHDOG_STARTUP_GRACE_SECONDS:-180" in compose
    assert "FAPAI_LOCAL_SOLVER_WATCHDOG_POLL_SECONDS:-30" in compose
    assert "FAPAI_NAS_AUTH_RECOVERY_CLIENT_ENABLED:-1" in compose
    assert "FAPAI_NAS_AUTH_RECOVERY_MARKER_PATH" in compose
    assert (
        "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE: /data/secrets/nas-auth-recovery.token"
        in compose
    )
    assert "FAPAI_LOCAL_SOLVER_EXECUTION_TIMEOUT_SECONDS=180" in env_example
    assert "FAPAI_LOCAL_SOLVER_TERMINATE_GRACE_SECONDS=5" in env_example
    assert "FAPAI_LOCAL_SOLVER_WATCHDOG_STALE_SECONDS=300" in env_example
    assert "FAPAI_NAS_AUTH_RECOVERY_CLIENT_ENABLED=1" in env_example
    assert (
        "FAPAI_NAS_AUTH_RECOVERY_SNAPSHOT_PATH: /app/.codex-temp/bridge-control/pc2-auth-snapshot.json"
        in compose
    )
    assert 'FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED: "1"' in compose
    assert compose.count("${FAPAI_HOST_DATA_GID:-1000}") == 2
    browser_section = compose.split("  pc2-browser-solver:", 1)[1].split(
        "  pc2-seed-1:", 1
    )[0]
    assert "FAPAI_CDP_ALLOWED_CLIENT_CIDRS" in browser_section
    assert "192.168.15.200/32" in browser_section
    secrets_mount = browser_section.split(
        "source: ${FAPAI_DATA_ROOT:?set FAPAI_DATA_ROOT}/secrets", 1
    )[1].split("- type: bind", 1)[0]
    assert "read_only: true" in secrets_mount


def test_linux_runtime_files_do_not_reference_windows_paths() -> None:
    runtime_files = (
        OPS_ROOT / "Dockerfile.browser",
        OPS_ROOT / "compose.yaml",
        OPS_ROOT / "start-browser-solver.sh",
        OPS_ROOT / "deploy.sh",
    )
    for path in runtime_files:
        text = _read(path).lower()
        assert "c:\\" not in text
        assert "powershell" not in text
        assert "schtasks" not in text


def test_browser_image_keeps_solver_and_os_mouse_in_one_display() -> None:
    dockerfile = _read(OPS_ROOT / "Dockerfile.browser")
    start_script = _read(OPS_ROOT / "start-browser-solver.sh")

    for package in (
        "xvfb",
        "fluxbox",
        "tigervnc-scraping-server",
        "tigervnc-tools",
        "xdotool",
        "novnc",
        "gnome-screenshot",
        "gcc",
        "libc6-dev",
        "linux-libc-dev",
        "Pillow==11.3.0",
        "evdev==1.9.2",
    ):
        assert package in dockerfile
    assert 'export DISPLAY="$display"' in start_script
    assert 'export XAUTHORITY="$xauthority"' in start_script
    assert 'touch "$XAUTHORITY"' in start_script
    assert "tools/pc2_local_solver.py" in start_script
    assert "--remote-debugging-port=9223" in start_script
    assert "tools/cdp_host_relay.py" in start_script
    assert "tools/cdp_browser_identity.py" in start_script
    assert "COPY tools/cdp_host_relay.py /app/tools/cdp_host_relay.py" in dockerfile
    assert (
        "COPY tools/cdp_browser_identity.py /app/tools/cdp_browser_identity.py"
        in dockerfile
    )
    assert (
        "COPY tools/pc2_solver_watchdog.py /app/tools/pc2_solver_watchdog.py"
        in dockerfile
    )
    for runtime_file in (
        "tools/internal_api_http.py",
        "tools/pc2_auth_recovery.py",
        "tools/pc2_local_solver.py",
        "tools/pc2_linux_healthcheck.py",
        "src/captcha_solver.py",
    ):
        assert f"COPY {runtime_file} /app/{runtime_file}" in dockerfile
    assert "--upstream-host 127.0.0.1" in start_script
    assert "--upstream-port 9223" in start_script
    assert "--allow-cidr" in start_script
    assert "CROW_CDP_ALLOWED_CLIENT_CIDRS" in start_script
    assert 'crow_env CROW_CDP_PUBLIC_PORT "9224"' in start_script
    assert "tools/pc2_solver_watchdog.py" in start_script
    assert 'crow_env CROW_LOCAL_SOLVER_WATCHDOG_STALE_SECONDS "300"' in start_script
    assert "EXPOSE 6080 9224" in dockerfile
    assert "USER fapaifang" in dockerfile
    assert "--no-sandbox" not in start_script
    assert "PC2 browser must run as the non-root fapaifang user" in start_script
    assert "unprivileged_userns_clone" in start_script
    assert "FAPAI_BROWSER_UID" in dockerfile
    assert (
        '[[ ! -r "$vnc_password_file" || ! -s "$vnc_password_file" ]]' in start_script
    )
    assert 'tigervncpasswd -f >"$vnc_auth_file"' in start_script
    assert "x0tigervncserver" in start_script
    assert "-SecurityTypes VncAuth" in start_script
    assert 'display="$(crow_select_xvfb_display "$display")"' in start_script
    assert 'rm -f "$display_lock" "$display_socket"' not in start_script


def test_browser_uses_a_pinned_official_chrome_with_a_coherent_identity() -> None:
    dockerfile = _read(OPS_ROOT / "Dockerfile.browser")
    compose = _read(OPS_ROOT / "compose.yaml")
    auth_recovery_dockerfile = _read(OPS_ROOT / "Dockerfile.auth-recovery")
    env_example = _read(OPS_ROOT / "env.example")
    start_script = _read(OPS_ROOT / "start-browser-solver.sh")

    assert "FAPAI_BROWSER_USER_AGENT: ${FAPAI_BROWSER_USER_AGENT:-}" in compose
    assert (
        "FAPAI_BROWSER_IDENTITY_FULL_VERSION: ${FAPAI_BROWSER_IDENTITY_FULL_VERSION:-}"
        in compose
    )
    assert "ARG FAPAI_GOOGLE_CHROME_VERSION=152.0.7977.64-1" in dockerfile
    assert "ARG FAPAI_GOOGLE_CHROME_SHA256=" in dockerfile
    assert "google-chrome-stable_${FAPAI_GOOGLE_CHROME_VERSION}_amd64.deb" in dockerfile
    assert "sha256sum -c -" in dockerfile
    assert "dpkg-query -W" in dockerfile
    assert "FAPAI_BROWSER_EXECUTABLE=/usr/bin/google-chrome-stable" in env_example
    assert (
        "FAPAI_BROWSER_USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        in env_example
    )
    assert "Chrome/152.0.0.0" in env_example
    assert "FAPAI_BROWSER_IDENTITY_FULL_VERSION=152.0.7977.64" in env_example
    assert 'browser_user_agent="$(crow_env CROW_BROWSER_USER_AGENT "")"' in start_script
    assert 'browser_executable="$(crow_env CROW_BROWSER_EXECUTABLE "")"' in start_script
    assert "/usr/bin/google-chrome-stable" in start_script
    assert "playwright.chromium.executable_path" in start_script
    assert '"$browser_executable" --version' in start_script
    assert '"$browser_executable" \\' in start_script
    assert "Configured browser identity version does not match" in start_script
    assert "Configured browser user agent does not match" in start_script
    assert 'browser_identity_args+=(--user-agent="$browser_user_agent")' in start_script
    assert '"${browser_identity_args[@]}"' in start_script
    assert "--accept-lang=zh-CN,zh \\" in start_script
    assert "--accept-lang=zh-CN,zh;q=" not in start_script
    assert "tools/cdp_browser_identity.py" in start_script
    assert "CROW_BROWSER_IDENTITY_READY_PATH" in start_script
    assert (
        "COPY --chmod=0755 ops/pc2-linux/start-browser-solver.sh /usr/local/bin/start-browser-solver"
        in auth_recovery_dockerfile
    )


def test_browser_enables_webgl_in_the_xvfb_runtime() -> None:
    graphics = _read(REPO_ROOT / "tools" / "pc2_browser_graphics.py")

    for flag in (
        "--ignore-gpu-blocklist",
        "--enable-webgl",
        "--enable-unsafe-swiftshader",
        "--use-gl=angle",
        "--use-angle=swiftshader",
    ):
        assert flag in graphics


def test_browser_prefers_the_logged_in_host_display_and_hardware_gpu() -> None:
    compose = _read(OPS_ROOT / "compose.yaml")
    env_example = _read(OPS_ROOT / "env.example")
    start_script = _read(OPS_ROOT / "start-browser-solver.sh")

    assert "FAPAI_BROWSER_DISPLAY_MODE: ${FAPAI_BROWSER_DISPLAY_MODE:-auto}" in compose
    assert "FAPAI_BROWSER_HOST_DISPLAY: ${FAPAI_BROWSER_HOST_DISPLAY:-:0}" in compose
    assert "source: /tmp/.X11-unix" in compose
    assert "- /dev/dri:/dev/dri" in compose
    assert "FAPAI_BROWSER_DISPLAY_MODE=auto" in env_example
    assert "FAPAI_BROWSER_HOST_DISPLAY=:0" in env_example
    assert "FAPAI_BROWSER_HOST_XAUTHORITY_DIR" not in compose
    assert "prepare_host_display_access" in _read(OPS_ROOT / "deploy.sh")
    assert 'xhost +SI:localuser:"${host_user:-$(id -un)}"' in _read(
        OPS_ROOT / "deploy.sh"
    )
    assert "xhost +SI:localuser:root" not in _read(OPS_ROOT / "deploy.sh")
    assert "xhost +SI:localuser:root" not in start_script
    assert "--ozone-platform=x11" in _read(
        REPO_ROOT / "tools" / "pc2_browser_graphics.py"
    )
    assert "about:blank >/tmp/chromium.log 2>&1 &" in start_script
    assert "python - \"$start_url\" <<'PY'" in start_script
    assert '"method": "Page.navigate"' in start_script
    assert "FAPAI_SOLVER_OS_INPUT_BACKEND: pyautogui" in compose
    assert "- /dev/uinput:/dev/uinput" in compose
    assert "FAPAI_SOLVER_OS_INPUT_BACKEND=pyautogui" in env_example
    auth_recovery_dockerfile = _read(OPS_ROOT / "Dockerfile.auth-recovery")
    assert "FROM scratch AS hotfix" in auth_recovery_dockerfile
    assert "COPY --from=hotfix / /" in auth_recovery_dockerfile
    assert (
        "COPY --chmod=0755 ops/pc2-linux/start-browser-solver.sh"
        in auth_recovery_dockerfile
    )
    assert "apt-get" not in auth_recovery_dockerfile
    assert "pip install" not in auth_recovery_dockerfile
    assert (
        "docker run --rm --entrypoint python \"$browser_base_image\" -c 'import evdev'"
        in _read(OPS_ROOT / "deploy.sh")
    )
    assert 'if [[ "$use_host_display" == "0" ]]; then' in start_script
    assert 'echo "Browser display mode: host ($display)"' in start_script
    assert 'solver_pid="$!"' in start_script
    assert 'pids+=("$solver_pid")' in start_script
    assert "crow_wait_children" in start_script
    assert "trap - EXIT INT TERM" in start_script


def test_browser_healthcheck_does_not_trigger_rfb_authentication() -> None:
    healthcheck = _read(REPO_ROOT / "tools" / "pc2_linux_healthcheck.py")

    assert "port: int = 5900" in healthcheck
    assert 'Path("/proc/net/tcp")' in healthcheck
    assert "_check_rfb_listener()" in healthcheck
    assert "invalid RFB banner" not in healthcheck
    assert '_process_exists("x0tigervncserver")' in healthcheck
    assert '_process_exists("websockify")' in healthcheck
    assert '_process_exists("tools/pc2_solver_watchdog.py")' in healthcheck
    assert "_check_solver_heartbeat()" in healthcheck


def test_rfb_listener_check_reads_proc_without_connecting(tmp_path: Path) -> None:
    proc_net_tcp = tmp_path / "tcp"
    proc_net_tcp.write_text(
        "  sl  local_address rem_address   st\n   0: 0100007F:170C 00000000:0000 0A\n",
        encoding="ascii",
    )

    pc2_linux_healthcheck._check_rfb_listener(proc_net_paths=(proc_net_tcp,))

    proc_net_tcp.write_text(
        "  sl  local_address rem_address   st\n   0: 0100007F:170C 00000000:0000 01\n",
        encoding="ascii",
    )
    with pytest.raises(RuntimeError, match="RFB server is not listening"):
        pc2_linux_healthcheck._check_rfb_listener(proc_net_paths=(proc_net_tcp,))


def test_browser_healthcheck_is_directly_executable() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "pc2_linux_healthcheck.py"),
            "--help",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_linux_compose_uses_compatibility_cdp_relay() -> None:
    compose = _read(OPS_ROOT / "compose.yaml")

    assert "http://pc2-browser-solver:9224" in compose
    assert "http://192.168.15.104:9224" in compose
    assert 'FAPAI_CDP_PUBLIC_PORT: "9224"' in compose
    assert ':9224:9224"' in compose
    assert ":9223:9223" not in compose


def test_deploy_script_has_identity_gate_and_rollback_links() -> None:
    deploy = _read(OPS_ROOT / "deploy.sh")

    assert '[[ "$(hostname -s)" == "pc2" ]]' in deploy
    assert "192\\.168\\.15\\.104" in deploy
    assert "^PROFILE=pc2$" in deploy
    assert "^EXPECTED_BOOT_MODE=uefi$" in deploy
    assert "sudo -n true" in deploy
    assert '"$app_root/current"' in deploy
    assert '"$app_root/previous"' in deploy
    assert "wait_for_health" in deploy
    assert "--skip-build" in deploy
    assert 'docker image inspect "$app_image"' in deploy
    assert 'docker image inspect "$browser_image"' in deploy
    assert "--browser-only" in deploy
    assert "wait_for_browser_health" in deploy
    assert "up -d --no-deps pc2-browser-solver" in deploy
    assert "Dockerfile.auth-recovery" in deploy
    assert "Browser hotfix layer build failed" in deploy
    assert '--build-arg "FAPAI_BASE_IMAGE=$app_image"' in deploy
    assert "docker system prune" not in deploy
    assert "rm -rf" not in deploy
    assert "check_capacity" in deploy
    assert "df -Pk" in deploy
    assert "df -Pi" in deploy
    assert "CROW_MIN_FREE_SPACE_PERCENT" in deploy
    assert "CROW_MIN_FREE_INODES_PERCENT" in deploy
    assert "Refusing deployment" in deploy


def test_pc2_auth_recovery_browser_hotfix_only_overlays_browser_side_files() -> None:
    dockerfile = _read(OPS_ROOT / "Dockerfile.auth-recovery")

    copy_lines = [
        line.strip() for line in dockerfile.splitlines() if line.startswith("COPY ")
    ]
    assert copy_lines == [
        "COPY tools/internal_api_http.py /app/tools/internal_api_http.py",
        "COPY tools/pc2_auth_recovery.py /app/tools/pc2_auth_recovery.py",
        "COPY tools/pc2_local_solver.py /app/tools/pc2_local_solver.py",
        "COPY tools/pc2_solver_*.py /app/tools/",
        "COPY tools/cdp_browser_identity.py /app/tools/cdp_browser_identity.py",
        "COPY tools/pc2_browser_graphics.py /app/tools/pc2_browser_graphics.py",
        "COPY tools/pc2_linux_healthcheck.py /app/tools/pc2_linux_healthcheck.py",
        "COPY src/captcha_solver.py /app/src/captcha_solver.py",
        "COPY src/project_environment.py /app/src/project_environment.py",
        "COPY --chmod=0755 ops/pc2-linux/start-browser-solver.sh /usr/local/bin/start-browser-solver",
        "COPY ops/pc2-linux/process-supervisor.sh /usr/local/bin/process-supervisor.sh",
        "COPY scripts/project-environment.sh /usr/local/bin/project-environment.sh",
        "COPY --from=hotfix / /",
    ]


def test_pc2_worker_hotfix_overlays_analysis_module_b_runtime_files() -> None:
    dockerfile = _read(OPS_ROOT / "Dockerfile.worker-hotfix")

    copy_lines = [
        line.strip() for line in dockerfile.splitlines() if line.startswith("COPY ")
    ]
    assert copy_lines == [
        "COPY tools/cdp_browser_identity.py /app/tools/cdp_browser_identity.py",
        "COPY tools/detail_worker.py /app/tools/detail_worker.py",
        "COPY tools/live_batch_smoke.py /app/tools/live_batch_smoke.py",
        "COPY src/analysis_ensemble.py /app/src/analysis_ensemble.py",
        "COPY src/llm_helper.py /app/src/llm_helper.py",
        "COPY src/storage/models.py /app/src/storage/models.py",
        "COPY src/storage/repository.py /app/src/storage/repository.py",
        "COPY alembic/versions/20260606_0008_add_seed_scan_rescan_state.py /app/alembic/versions/20260606_0008_add_seed_scan_rescan_state.py",
        "COPY alembic/versions/20260901_0009_add_analysis_ensemble_runs.py /app/alembic/versions/20260901_0009_add_analysis_ensemble_runs.py",
    ]


def test_shell_scripts_pass_bash_syntax_check() -> None:
    bash_executable = shutil.which("bash")
    git_executable = shutil.which("git")
    if git_executable:
        git_bash = Path(git_executable).resolve().parents[1] / "bin" / "bash.exe"
        if git_bash.is_file():
            bash_executable = str(git_bash)
    assert bash_executable, "bash is required for the PC2 deployment contract test"
    for path in (OPS_ROOT / "deploy.sh", OPS_ROOT / "start-browser-solver.sh"):
        result = subprocess.run(
            [bash_executable, "-n"],
            check=False,
            capture_output=True,
            input=_read(path).encode("utf-8"),
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
