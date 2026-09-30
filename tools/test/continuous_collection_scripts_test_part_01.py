from __future__ import annotations

from tools.test.continuous_collection_scripts_test_context import *


def test_generate_all_seed_jobs_script_writes_host_jobs_file_safely() -> None:
    script = _script("generate-all-seed-jobs.ps1")

    assert "tools\\generate_seed_jobs.py" in script
    assert "CROW_DATA_ROOT_HOST" in script
    assert "seed_jobs_all.json" in script
    assert "datas\\all_locations.json" in script
    assert "CROW_SEED_JOBS_FILE" in script
    assert ".ProviderPath" in script
    assert "PYTHONPATH" in script


def test_taobao_login_watchdog_opens_official_verification_and_refreshes_snapshot() -> None:
    script = _script("taobao-login-watchdog.ps1")

    assert "check-taobao-login-health.ps1" in script
    assert "-SampleUrl" in script
    assert "start-taobao-cdp-browser.ps1" in script
    assert "export-taobao-cookie-snapshot.ps1" in script
    assert '[string]$OutputPath = ""' in script
    assert 'if ($OutputPath)' in script
    assert '"-OutputPath"' in script
    assert "complete Taobao official verification" in script
    assert "FapaiFangTaobaoLoginWatchdog" in script
    assert "Start-Process" in script
    assert "RedirectStandardOutput" in script
    assert "RedirectStandardError" in script
    assert "ExitCode" in script
    assert "cookie value" in script
    assert "cookie2=" not in script
    assert "sgcookie=" not in script
    assert "_tb_token_=" not in script
    assert "--remove-orphans" not in script


def test_taobao_login_watchdog_can_start_browser_with_system_proxy() -> None:
    script = _script("taobao-login-watchdog.ps1")

    assert "[switch]$UseSystemProxy" in script
    assert "if ($UseSystemProxy)" in script
    assert '"-UseSystemProxy"' in script


def test_taobao_login_watchdog_can_trigger_captcha_solver() -> None:
    script = _script("taobao-login-watchdog.ps1")

    assert "[switch]$TriggerCaptchaSolver" in script
    assert "CROW_CAPTCHA_SOLVER_ENABLED" in script
    assert '"-TriggerCaptchaSolver"' in script


def test_run_local_mock_slider_regression_script_uses_local_mock_regression_commands() -> None:
    script = _script("run-local-mock-slider-regression.ps1")

    assert "[int]$Runs = 3" in script
    assert "[int]$Workers = 4" in script
    assert "[switch]$SkipPytest" in script
    assert "[switch]$SkipMatrix" in script
    assert "[switch]$Headed" in script
    assert "test_mock_slider_drag_check.py" in script
    assert "test_mock_solver_probe.py" in script
    assert "test_mock_solver_matrix.py" in script
    assert "test_captcha_solver.py" in script
    assert "test_taobao_login_health.py" in script
    assert "test_detail_worker.py" in script
    assert "tools/mock_solver_matrix.py" in script
    assert "--scenario" in script
    assert "Local mock slider regression passed." in script


def test_register_taobao_login_watchdog_task_registers_on_demand_visible_user_task() -> None:
    script = _script("register-taobao-login-watchdog-task.ps1")

    assert "New-ScheduledTaskAction" in script
    assert "New-ScheduledTaskTrigger" not in script
    assert "Register-ScheduledTask" in script
    assert "FapaiFangTaobaoLoginWatchdog" in script
    assert "taobao-login-watchdog.ps1" in script
    assert '[string]$OutputPath = ""' in script
    assert '"-OutputPath"' in script
    assert "Interactive" in script
    assert "Convert-DataRootForScheduledTask" in script
    assert "On-demand FapaiFang Taobao recovery task" in script
    assert "recovery monitor starts it only" in script
    assert "IntervalMinutes" not in script


def test_register_taobao_login_watchdog_task_can_use_system_proxy() -> None:
    script = _script("register-taobao-login-watchdog-task.ps1")

    assert "[switch]$UseSystemProxy" in script
    assert "if ($UseSystemProxy)" in script
    assert '"-UseSystemProxy"' in script


def test_trigger_taobao_login_recovery_if_needed_uses_db_signals_and_safe_watchdog() -> None:
    script = _script("trigger-taobao-login-recovery-if-needed.ps1")

    assert "fapai_seed_item" in script
    assert "fapai_seed_scan_progress" in script
    assert "list_payload_missing" in script
    assert "FapaiFangTaobaoLoginWatchdog" in script
    assert "Get-ScheduledTask" in script
    assert "Start-ScheduledTask" in script
    assert "LastTriggeredAt" in script
    assert "RecoveryCooldownMinutes" in script
    assert "triggered_official_watchdog" in script
    assert "watchdog_already_running" in script
    assert "cookie value" in script
    assert "apiStatusForManualCheck.captcha_solver" in script
    assert "manual_required" in script
    assert '[int]$ManualAuthGraceMinutes = 30' in script
    assert "manual_only" in script
    assert "manual_auth_grace_period" in script
    assert "automatic_solver_recovery_in_progress" in script
    assert "function Stop-DedicatedRecoveryBrowser" in script
    assert "remote-debugging-port=9225" in script
    assert "closed_recovery_browser_count" in script
    grace_start = script.index('status = "manual_auth_grace_period"')
    grace_end = script.index("exit 0", grace_start)
    grace_block = script[grace_start:grace_end]
    assert "closed_recovery_browser_count" in grace_block
    assert "Stop-DedicatedRecoveryBrowser" in script[:grace_start]
    manual_check_index = script.index("$manualAuthRequired = $false")
    pause_guard_index = script.index("if ($snapshot.collection_paused -eq $true")
    assert manual_check_index < pause_guard_index
    assert "if ($snapshot.collection_paused -eq $true -and -not $manualAuthRequired)" in script
    assert "Input.dispatchMouseEvent" not in script
    assert "cookie2=" not in script
    assert "sgcookie=" not in script
    assert "_tb_token_=" not in script
    assert "--remove-orphans" not in script


def test_register_taobao_login_recovery_monitor_task_registers_fast_interactive_monitor() -> None:
    script = _script("register-taobao-login-recovery-monitor-task.ps1")

    assert "New-ScheduledTaskAction" in script
    assert "New-ScheduledTaskTrigger" in script
    assert "Register-ScheduledTask" in script
    assert "FapaiFangTaobaoLoginRecoveryMonitor" in script
    assert "trigger-taobao-login-recovery-if-needed.ps1" in script
    assert "Interactive" in script
    assert "MultipleInstances IgnoreNew" in script
    assert "IntervalMinutes" in script
    assert "MinRecentSeedItems" in script
    assert "StaleSeedMinutes" in script
    assert '[int]$ManualAuthGraceMinutes = 30' in script
    assert "-ManualAuthGraceMinutes" in script
    assert "Convert-DataRootForScheduledTask" in script
    assert "Convert-ToPowerShellSingleQuotedArgument" in script
    assert "run-taobao-login-recovery-monitor.ps1" in script
    assert "taobao-login-recovery-monitor.log" in script
    assert "$wrapperScript" in script
    assert "$taskWorkingDirectory = $runtimeDir" in script
    assert '"`"$wrapperScript`""' in script
    assert "-WorkingDirectory $taskWorkingDirectory" in script
    assert '"`"$TaskPath`""' not in script
    assert "--remove-orphans" not in script


def test_register_pc1_shared_auth_maintenance_registers_watchdog_and_nas_recovery_with_port_9225() -> None:
    script = _script("register-pc1-shared-auth-maintenance.ps1")

    assert '[int]$Port = 9225' in script
    assert '[string]$ApiBase = ""' in script
    assert '[string]$ApiCaFile = ""' in script
    assert 'ConvertTo-CollectionApiOrigin' in script
    assert 'http://192.168.15.200:8001/api' not in script
    assert "register-taobao-login-watchdog-task.ps1" in script
    assert "register-pc1-nas-auth-recovery-task.ps1" in script
    assert 'Join-Path $resolvedDataRoot "secrets\\nodes\\pc2\\taobao-cookies.json"' in script
    assert 'Enable-ScheduledTask -TaskName "FapaiFangTaobaoLoginWatchdog"' in script
    assert 'Enable-ScheduledTask -TaskName "FapaiFangNasAuthRecovery"' in script
    assert 'Disable-ScheduledTask -TaskName "FapaiFangTaobaoLoginRecoveryMonitor"' in script
    assert '[switch]$StartWatchdogNow' in script
    assert '[int]$ManualAuthGraceMinutes = 30' in script
    assert '[int]$LoginWindowSeconds = 300' in script
    assert '"-LoginWindowSeconds", $LoginWindowSeconds' in script
    assert '"-ProfileDir", $ProfileDir' in script
    assert '"-BrowserPath", $BrowserPath' in script
    assert '"-ExecutionTimeLimitMinutes", $NasRecoveryExecutionTimeLimitMinutes' in script
    assert '"-ApiCaFile", $ApiCaFile' in script
    assert 'Start-ScheduledTask -TaskName "FapaiFangTaobaoLoginWatchdog"' in script
    assert "WatchdogIntervalMinutes" not in script


def test_pc1_nas_auth_recovery_watcher_keeps_single_window_and_publishes_only_metadata() -> None:
    script = _script("watch-pc1-nas-auth-recovery.ps1")

    assert '[int]$LoginWindowSeconds = 300' in script
    assert "Get-Command curl.exe" in script
    assert "--max-time 3" in script
    assert "$request.KeepAlive = $false" in script
    assert "$stream.ReadTimeout = 3000" in script
    assert '$withinWindow' in script
    assert 'Get-Pc1RecoveryTab' in script
    assert 'if ($null -eq $authTab -and -not $withinWindow)' in script
    assert 'Show-Pc1RecoveryPrompt' in script
    assert '-TargetId $authTab.id' in script
    assert '-AllowListOnly' not in script
    assert 'last_probe_exit_code' in script
    assert 'complete-pc1-inplace-auth.ps1' in script
    assert 'resolve-pc1-auth-python.ps1' in script
    assert 'Resolve-Pc1AuthPython' in script
    assert 'Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256' in script
    assert 'Invoke-Pc1RecoveryApi' in script
    assert 'secrets\\nas-auth-recovery.token' in script
    assert 'Move-Item -LiteralPath $temporaryPath -Destination $Path -Force' in script
    assert '-Action snapshot_ready' in script
    assert 'cookie_count = $cookies.Count' in script
    assert 'cookie_value' not in script
    assert 'cookies =' not in script.split('snapshot_ready', 1)[1]


def test_pc1_auto_resume_rejects_implicit_remote_http_default() -> None:
    script = _script("watch-pc1-auth-auto-resume.ps1")

    assert "ConvertTo-CollectionApiOrigin" in script
    assert "An explicit HTTPS API origin or protected loopback tunnel is required" in script
    assert "http://192.168.15.200:8001/api" not in script


def test_recovery_trigger_rejects_implicit_remote_http_default() -> None:
    script = _script("trigger-taobao-login-recovery-if-needed.ps1")

    assert "An explicit HTTPS API origin or protected loopback tunnel is required" in script
    assert "ConvertTo-CollectionApiOrigin" in script
    assert "http://192.168.15.200:8001/api" not in script


def test_register_pc1_nas_auth_recovery_task_is_interactive_single_flight() -> None:
    script = _script("register-pc1-nas-auth-recovery-task.ps1")

    assert 'FapaiFangNasAuthRecovery' in script
    assert 'watch-pc1-nas-auth-recovery.ps1' in script
    assert 'New-ScheduledTaskTrigger' in script
    assert 'MultipleInstances IgnoreNew' in script
    assert 'LogonType Interactive' in script
    assert 'LoginWindowSeconds must be at least 300' in script
    assert '"-TokenPath", "`"$TokenPath`""' in script
    assert '"-Python", "`"$resolvedPython`""' in script
    assert '"-ProfileDir", "`"$ProfileDir`""' in script
    assert '"-BrowserPath", "`"$BrowserPath`""' in script
    assert 'ExecutionTimeLimit (New-TimeSpan -Minutes $ExecutionTimeLimitMinutes)' in script


def test_desktop_runtime_config_pins_python_with_requests_preflight() -> None:
    script = _script("write-collector-desktop-runtime-config.ps1")

    assert "resolve-pc1-auth-python.ps1" in script
    assert "Resolve-Pc1AuthPython" in script
    assert "CROW_DESKTOP_PYTHON_PATH = $resolvedPython" in script


def test_deploy_pc2_llm_helper_hotfix_uses_ssh_hash_verification_and_optional_analysis_restart() -> None:
    script = _script("deploy-pc2-llm-helper-hotfix.ps1")

    assert "Get-FileHash -LiteralPath $resolvedLocalPath -Algorithm SHA256" in script
    assert "Convert-ToScpRemotePath" in script
    assert "scp.exe" in script
    assert "$remoteScpPath" in script
    assert "PC2 llm_helper hotfix staging copy failed" in script
    assert "pc2-real-analysis-1" in script
    assert "Stop-Process -Id $process.ProcessId -Force" in script


def test_optimize_pc2_external_cdp_host_only_targets_unused_local_9223_edge_profile() -> None:
    script = _script("optimize-pc2-external-cdp-host.ps1")

    assert '[switch]$Apply' in script
    assert "FAPAI_CDP_EXTERNAL" in script
    assert "http://127.0.0.1:9223" in script
    assert "edge-cdp-profile-pc2" in script
    assert "Test-CdpEndpoint" in script
    assert "would_stop_unused_local_browser" in script
    assert "stopped_unused_local_browser" in script
    assert "Stop-Process -Id `$process.ProcessId -Force" in script


def test_register_continuous_collection_task_registers_health_gated_collection_task() -> None:
    script = _script("register-continuous-collection-task.ps1")

    assert "New-ScheduledTaskAction" in script
    assert "New-ScheduledTaskTrigger" in script
    assert "Register-ScheduledTask" in script
    assert "FapaiFangContinuousCollection" in script
    assert "start-continuous-collection.ps1" in script
    assert "Interactive" in script
    assert "MultipleInstances IgnoreNew" in script
    assert "Convert-DataRootForScheduledTask" in script
    assert "-SkipLoginWatchdog" not in script
    assert "-SkipDockerStart" not in script
    assert "--remove-orphans" not in script
    assert "docker-compose.postgres" not in script


def test_start_continuous_collection_generates_jobs_checks_login_and_starts_workers() -> None:
    script = _script("start-continuous-collection.ps1")

    assert "generate-all-seed-jobs.ps1" in script
    assert "start-taobao-cdp-browser.ps1" in script
    assert "taobao-login-watchdog.ps1" in script
    assert "export-taobao-cookie-snapshot.ps1" in script
    assert "docker compose" in script
    assert "fapaifang-seed-collector" in script
    assert "fapaifang-seed-collector-2" in script
    assert "crow-api" in script
    assert "fapaifang-detail-worker" in script
    assert "fapaifang-detail-analysis-worker" in script
    assert "fapaifang-detail-analysis-worker-3" in script
    assert '"--profile", "api"' in script
    assert '"--profile", "analysis"' in script
    assert "CROW_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json" in script
    assert "CROW_COOKIE_SNAPSHOT=/data/secrets/taobao-cookies.json" in script
    assert "CROW_SEED_PAGES_PER_RUN=20" in script
    assert "CROW_SEED_LOOP_INTERVAL_SECONDS=60" in script
    assert "CROW_SEED_PARALLEL_SORTS=1" in script
    assert "CROW_DETAIL_TARGET_SUCCESS=10" in script
    assert "CROW_DETAIL_MAX_ATTEMPTS=30" in script
    assert "CROW_DETAIL_LOOP_INTERVAL_SECONDS=30" in script
    assert "CROW_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS=0" in script
    assert "CROW_DETAIL_ANALYSIS_TARGET_SUCCESS=10" in script
    assert "CROW_DETAIL_ANALYSIS_MAX_ATTEMPTS=20" in script
    assert "CROW_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS=30" in script
    assert "CROW_DETAIL_ANALYSIS_ACTIVE_LOOP_INTERVAL_SECONDS=0" in script
    assert "CROW_SEED_RESCAN_INTERVAL_SECONDS=900" in script
    assert "CROW_SEED_FAILURE_COOLDOWN_THRESHOLD=3" in script
    assert "CROW_SEED_FAILURE_COOLDOWN_SECONDS=1800" in script
    assert "CROW_DETAIL_FAILURE_COOLDOWN_THRESHOLD=3" in script
    assert "CROW_DETAIL_FAILURE_COOLDOWN_SECONDS=1800" in script
    assert "CROW_DETAIL_ANALYSIS_WORKER_RESTART" in script
    assert "CROW_DETAIL_ANALYSIS_WORKER_2_RESTART" in script
    assert "CROW_DETAIL_ANALYSIS_WORKER_3_RESTART" in script
    assert "-SampleUrl" in script
    assert "200782003__1.htm" in script
    assert "--remove-orphans" not in script
    assert "docker-compose.postgres" not in script


def test_collection_compose_defines_seed_and_detail_worker_pools() -> None:
    compose = REPO_ROOT.joinpath("docker-compose.collection.yml").read_text(encoding="utf-8")
    host_bind = REPO_ROOT.joinpath("docker-compose.collection.host-bind.yml").read_text(encoding="utf-8")

    for service_name in (
        "fapaifang-seed-collector-2:",
        "fapaifang-seed-collector-3:",
        "fapaifang-seed-collector-4:",
        "fapaifang-seed-collector-5:",
        "fapaifang-seed-collector-6:",
        "fapaifang-detail-worker-2:",
        "fapaifang-detail-worker-3:",
        "fapaifang-detail-analysis-worker:",
        "fapaifang-detail-analysis-worker-2:",
        "fapaifang-detail-analysis-worker-3:",
    ):
        assert service_name in compose
        assert service_name in host_bind
    assert "FAPAI_SEED_JOBS_FILE: ${FAPAI_SEED_JOBS_FILE:-}" in compose
    assert "FAPAI_SEED_PARALLEL_SORTS: ${FAPAI_SEED_PARALLEL_SORTS:-1}" in compose
    assert "FAPAI_SEED_PAGES_PER_RUN: ${FAPAI_SEED_PAGES_PER_RUN:-20}" in compose
    assert "FAPAI_SEED_LOOP_INTERVAL_SECONDS: ${FAPAI_SEED_LOOP_INTERVAL_SECONDS:-60}" in compose
    assert "FAPAI_DETAIL_TARGET_SUCCESS: ${FAPAI_DETAIL_TARGET_SUCCESS:-10}" in compose
    assert "FAPAI_DETAIL_MAX_ATTEMPTS: ${FAPAI_DETAIL_MAX_ATTEMPTS:-30}" in compose
    assert "FAPAI_DETAIL_LOOP_INTERVAL_SECONDS: ${FAPAI_DETAIL_LOOP_INTERVAL_SECONDS:-30}" in compose
    assert "FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS: ${FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS:-0}" in compose
    assert "FAPAI_DETAIL_TARGET_SUCCESS: ${FAPAI_DETAIL_ANALYSIS_TARGET_SUCCESS:-10}" in compose
    assert "FAPAI_DETAIL_MAX_ATTEMPTS: ${FAPAI_DETAIL_ANALYSIS_MAX_ATTEMPTS:-20}" in compose
    assert "FAPAI_DETAIL_LOOP_INTERVAL_SECONDS: ${FAPAI_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS:-30}" in compose
    assert "FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS: ${FAPAI_DETAIL_ANALYSIS_ACTIVE_LOOP_INTERVAL_SECONDS:-0}" in compose
    assert "FAPAI_SEED_WORKER_ID: ${FAPAI_SEED_WORKER_ID_2:-seed-2}" in compose
    assert "FAPAI_DETAIL_WORKER_ID: ${FAPAI_DETAIL_WORKER_ID_2:-detail-2}" in compose
    assert "FAPAI_OUTPUT_DIR: /data/output/detail_analysis_worker_2" in compose
    assert "FAPAI_DETAIL_WORKER_ID: ${FAPAI_DETAIL_ANALYSIS_WORKER_ID_2:-analysis-2}" in compose


def test_collection_entrypoints_can_start_cdp_with_system_proxy() -> None:
    for name in (
        "start-continuous-collection.ps1",
        "start-seed-scan-only.ps1",
        "start-detail-analysis-only.ps1",
    ):
        script = _script(name)

        assert "[switch]$UseSystemProxy" in script
        assert "$startBrowserArgs" in script
        assert "$watchdogArgs" in script
        assert "if ($UseSystemProxy)" in script
        assert '"-UseSystemProxy"' in script


def test_pc2_host_worker_env_disables_runtime_db_bootstrap_and_browser_page_scan() -> None:
    script = _pc2_host_script("load-host-worker-env.ps1")

    assert "CROW_DB_AUTO_CREATE" in script
    assert "'0'" in script
    assert "CROW_DB_ENABLE_POSTGIS" in script
    assert "CROW_DETAIL_LOAD_OPEN_BROWSER_PAGES" in script
    assert "CROW_API_BASE_URL" in script
    assert "CROW_REPORT_CDP_ENDPOINT" in script
    assert "CROW_NODE_ID" in script
    assert "Set-CrowEnvironmentValue -Name 'CROW_COOKIE_SNAPSHOT_PREFER' -Value ('0')" in script


def test_pc2_host_seed_worker_uses_resident_loop_without_single_run_cap() -> None:
    script = _pc2_host_script("start-host-seed-worker.ps1")

    assert "CROW_HOST_SEED_WORKER_ID" in script
    assert "CROW_LIST_BROWSER_FALLBACK" in script
    assert "'1'" in script
    assert "if (-not (Get-CrowEnvironmentValue -Name 'CROW_LIST_BROWSER_FALLBACK'))" in script
    assert "'--loop'" in script
    assert "CROW_SEED_PAGES_PER_RUN" in script
    assert "'--active-loop-interval-seconds', '10'" in script
    assert "'--loop-interval-seconds', '60'" in script
    assert "'--auth-probe-interval-seconds', '10'" in script
    assert "CROW_SEED_FAILURE_COOLDOWN_THRESHOLD" in script
    assert "CROW_SEED_FAILURE_COOLDOWN_SECONDS" in script
    assert "'--pages-per-run', '5'" not in script
    assert "'--failure-cooldown-threshold', '1'" not in script
    assert "'--failure-cooldown-seconds', '600'" not in script
    assert "'--max-runs'" not in script


def test_pc2_host_seed_worker_2_wraps_primary_seed_worker_with_distinct_worker_id() -> None:
    script = _pc2_host_script("start-host-seed-worker-2.ps1")

    assert "CROW_HOST_SEED_WORKER_ID" in script
    assert "pc2-host-seed-2" in script
    assert "start-host-seed-worker.ps1" in script


def test_pc2_host_detail_worker_uses_resident_loop_and_small_batch_target() -> None:
    script = _pc2_host_script("start-host-detail-worker.ps1")

    assert "CROW_HOST_DETAIL_WORKER_ID" in script
    assert "'--loop'" in script
    assert "'--target-success', '2'" in script
    assert "'--max-attempts', '6'" in script
    assert "'--active-loop-interval-seconds', '10'" in script
    assert "'--loop-interval-seconds', '60'" in script
    assert "'--failure-cooldown-seconds', '120'" in script
    assert "'--solver-enabled'" in script
