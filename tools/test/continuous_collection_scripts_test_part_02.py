from __future__ import annotations

from tools.test.continuous_collection_scripts_test_context import *


def test_pc2_host_direct_nas_env_maps_home_share_and_uses_real_pc2_cdp_endpoint() -> None:
    script = _pc2_host_script("load-host-direct-nas-env.ps1")

    assert "cmdkey /add:192.168.15.200" in script
    assert "net use \\\\192.168.15.200\\home" in script
    assert "\\\\192.168.15.200\\home\\project\\project\\FPFData" in script
    assert "$cdpEndpoint = if ($env:FAPAI_CDP_ENDPOINT)" in script
    assert "http://127.0.0.1:9223" in script
    assert "$reportCdpEndpoint = if ($env:FAPAI_REPORT_CDP_ENDPOINT)" in script
    assert "http://192.168.15.104:9224" in script
    assert "$cookieSnapshotPrefer = if ($env:FAPAI_COOKIE_SNAPSHOT_PREFER)" in script
    assert "SetEnvironmentVariable('FAPAI_NODE_ID', 'pc2', 'Process')" in script


def test_pc2_host_direct_nas_env_loads_env_file_before_reading_share_credentials() -> None:
    script = _pc2_host_script("load-host-direct-nas-env.ps1")

    env_file_index = script.index("if (Test-Path $envFile)")
    share_user_index = script.index("$shareUser = [string]($env:FAPAI_NAS_SHARE_USER)")
    share_password_index = script.index("$sharePassword = [string]($env:FAPAI_NAS_SHARE_PASSWORD)")

    assert env_file_index < share_user_index < share_password_index


def test_pc2_host_direct_nas_env_maps_worker_node_detail_browser_flags() -> None:
    script = _pc2_host_script("load-host-direct-nas-env.ps1")

    assert "$listBrowserFallback = if ($env:FAPAI_LIST_BROWSER_FALLBACK)" in script
    assert "$detailBrowserFallback = if ($env:FAPAI_DETAIL_BROWSER_FALLBACK)" in script
    assert "$detailLoadOpenBrowserPages = if ($env:FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES)" in script
    assert "$detailCdpEndpoint = if ($env:FAPAI_DETAIL_CDP_ENDPOINT)" in script
    assert "$seedCaptchaSolverEnabled = if ($env:FAPAI_SEED_CAPTCHA_SOLVER_ENABLED)" in script
    assert "$detailCaptchaSolverEnabled = if ($env:FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED)" in script
    assert "$captchaSolverEnabled = if ($env:FAPAI_CAPTCHA_SOLVER_ENABLED) { $env:FAPAI_CAPTCHA_SOLVER_ENABLED } else { '1' }" in script
    assert "$realTaobaoAutoSolverEnabled = if ($env:FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED)" in script
    assert "SetEnvironmentVariable('FAPAI_LIST_BROWSER_FALLBACK'" in script
    assert "SetEnvironmentVariable('FAPAI_DETAIL_BROWSER_FALLBACK'" in script
    assert "SetEnvironmentVariable('FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES'" in script
    assert "SetEnvironmentVariable('FAPAI_CAPTCHA_SOLVER_ENABLED', $captchaSolverEnabled" in script
    assert "SetEnvironmentVariable('FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED', $realTaobaoAutoSolverEnabled" in script
    assert "SetEnvironmentVariable('FAPAI_SEED_CAPTCHA_SOLVER_ENABLED'" in script
    assert "SetEnvironmentVariable('FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED'" in script
    assert "SetEnvironmentVariable('FAPAI_DETAIL_CDP_ENDPOINT'" in script


def test_pc2_cookie_only_env_cutover_preserves_unrelated_settings_and_requires_snapshot() -> None:
    script = _pc2_host_script("apply-cookie-only-worker-env.ps1")

    assert "ReadAllLines" in script
    assert "WriteAllLines" in script
    assert "UTF8Encoding($false)" in script
    assert "CROW_LIST_BROWSER_FALLBACK = '0'" in script
    assert "CROW_DETAIL_BROWSER_FALLBACK = '0'" in script
    assert "CROW_DETAIL_LOAD_OPEN_BROWSER_PAGES = '0'" in script
    assert "CROW_COOKIE_SNAPSHOT_PREFER = '1'" in script
    assert "CROW_CAPTCHA_SOLVER_ENABLED = '0'" in script
    assert "CROW_HOST_DETAIL_WORKER_COUNT = '4'" in script
    assert "CROW_HOST_ANALYSIS_WORKER_COUNT = '4'" in script
    assert "detail_worker_count = 4" in script
    assert "analysis_worker_count = 4" in script
    assert "$null = & $nasLoader" in script
    assert "if (-not (Test-Path -LiteralPath $SnapshotPath))" in script

    assert "Get-CrowEnvironmentNames -Name $entry.Key" in script


def test_pc2_cookie_only_install_script_backs_up_validates_and_restarts_watchdog() -> None:
    script = _pc2_host_script("install-cookie-only-runtime.ps1")

    assert "staging\\cookie-only-runtime" in script
    assert "backup\\pc2-cookie-only-runtime" in script
    assert "apply-cookie-only-worker-env.ps1" in script
    assert "register-host-direct-worker-watchdog.ps1" in script
    assert "start-host-direct-analysis-worker-2.ps1" in script
    assert "start-host-direct-analysis-worker-3.ps1" in script
    assert "Parser]::ParseFile" in script
    assert "Stop-ScheduledTask" in script
    assert "Copy-Item" in script
    assert "ConvertFrom-Json" in script
    assert "env.worker.local" in script
    assert "Get-ScheduledTask" in script
    assert "detail_worker_count = $cutover.detail_worker_count" in script
    assert "analysis_worker_count = $cutover.analysis_worker_count" in script
    assert "ConvertTo-Json -Compress" in script


def test_pc2_concurrency_env_only_updates_bounded_worker_counts() -> None:
    script = _pc2_host_script("apply-worker-concurrency-env.ps1")

    assert "[ValidateRange(3, 8)][int]$DetailWorkerCount = 4" in script
    assert "[ValidateRange(3, 8)][int]$AnalysisWorkerCount = 4" in script
    assert "CROW_HOST_DETAIL_WORKER_COUNT = [string]$DetailWorkerCount" in script
    assert "CROW_HOST_ANALYSIS_WORKER_COUNT = [string]$AnalysisWorkerCount" in script
    assert "ReadAllLines" in script
    assert "WriteAllLines" in script
    assert "UTF8Encoding($false)" in script
    assert "unrelated_settings_preserved = $true" in script
    assert "CROW_CAPTCHA_SOLVER_ENABLED" not in script
    assert "OPENAI_MODEL" not in script

    assert "Get-CrowEnvironmentNames -Name $entry.Key" in script


def test_pc2_concurrency_installer_backs_up_and_preserves_auth_and_model_settings() -> None:
    script = _pc2_host_script("install-concurrency-runtime.ps1")

    assert "staging\\concurrency-runtime" in script
    assert "backup\\pc2-concurrency-runtime" in script
    assert "apply-worker-concurrency-env.ps1" in script
    assert "launch-host-direct-workers.ps1" in script
    assert "start-host-direct-analysis-worker.ps1" in script
    assert "start-host-direct-detail-worker.ps1" in script
    assert "Parser]::ParseFile" in script
    assert "Stop-ScheduledTask" in script
    assert "env.worker.local" in script
    assert "register-host-direct-worker-watchdog.ps1" in script
    assert "unrelated_settings_preserved" in script
    assert "FAPAI_CAPTCHA_SOLVER_ENABLED" not in script
    assert "OPENAI_MODEL" not in script


def test_pc2_host_direct_seed_worker_uses_db_queue_and_short_loop_for_pc2_real_cutover() -> None:
    script = _pc2_host_script("start-host-direct-seed-worker.ps1")

    assert "load-host-direct-nas-env.ps1" in script
    assert "pc2-real-seed-1" in script
    assert "output\\nodes\\pc2-real\\seed_collector" in script
    assert "'--pages-per-run', '5'" in script
    assert "'--active-loop-interval-seconds', '5'" in script
    assert "'--loop-interval-seconds', '30'" in script
    assert "'--auth-probe-interval-seconds', '10'" in script
    assert "'--failure-cooldown-threshold', '10'" in script
    assert "'--failure-cooldown-seconds', '120'" in script
    assert "'--manual-challenge-reporting'" in script
    assert "manual_captcha_report_v1" in script
    assert "$manualChallengeReportingSupported = $true" in script
    assert "$manualChallengeReportingSupported = $false" not in script
    assert "elseif ($manualChallengeReportingSupported)" in script
    assert "$apiStatusReachable -and" not in script
    assert "-not $manualChallengeReportingSupported -and" not in script
    assert "'--solver-enabled'" in script
    assert "$solverEnabled = if ($env:FAPAI_SEED_CAPTCHA_SOLVER_ENABLED)" in script
    assert "-in @('1', 'true', 'yes', 'on')" in script
    assert "SetEnvironmentVariable('FAPAI_LIST_BROWSER_FALLBACK', '0', 'Process')" in script
    assert "FAPAI_LIST_HTTP_TIMEOUT_SECONDS" in script
    assert "FAPAI_LIST_BROWSER_RECOVERY_MAX_ATTEMPTS" in script
    assert "FAPAI_LIST_BROWSER_RECOVERY_WAIT_SECONDS" in script
    assert "'--job-key'" not in script
    assert "'--jobs-file'" not in script


def test_pc2_host_direct_seed_worker_regenerates_missing_seed_jobs_file_before_start() -> None:
    script = _pc2_host_script("start-host-direct-seed-worker.ps1")

    assert "$jobsFile = Join-Path $ctx.SharedRoot 'jobs\\seed_jobs_all.json'" in script
    assert "if (-not (Test-Path -LiteralPath $jobsFile))" in script
    assert "generate-all-seed-jobs.ps1" in script
    assert "-DataRoot $ctx.SharedRoot" in script
    assert "-Python $ctx.Python" in script


def test_pc2_host_direct_detail_worker_uses_raw_capture_loop_for_pc2_real_cutover() -> None:
    script = _pc2_host_script("start-host-direct-detail-worker.ps1")

    assert "[string]$RequestedWorkerId = ''" in script
    assert "[string]$RequestedOutputDir = ''" in script
    assert "[string]$BrowserFallbackOverride = ''" in script
    assert "if ($RequestedWorkerId)" in script
    assert "if ($RequestedOutputDir)" in script
    assert "if ($BrowserFallbackOverride -ne '')" in script
    assert "'[\"'']?(?=\\s|$)'" in script
    assert "load-host-direct-nas-env.ps1" in script
    assert "pc2-real-detail-1" in script
    assert "output\\nodes\\pc2-real\\detail_worker" in script
    assert "$targetSuccess = if ($env:FAPAI_HOST_DETAIL_TARGET_SUCCESS) { $env:FAPAI_HOST_DETAIL_TARGET_SUCCESS } else { '10' }" in script
    assert "$maxAttempts = if ($env:FAPAI_HOST_DETAIL_MAX_ATTEMPTS) { $env:FAPAI_HOST_DETAIL_MAX_ATTEMPTS } else { '30' }" in script
    assert "'--target-success', $targetSuccess" in script
    assert "'--max-attempts', $maxAttempts" in script
    assert "'--item-max-attempts', '3'" in script
    assert "'--failure-cooldown-seconds', '120'" in script
    assert "$activeLoopIntervalSeconds = if ($env:FAPAI_HOST_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS) { $env:FAPAI_HOST_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS } else { '0' }" in script
    assert "$successDelaySeconds = if ($env:FAPAI_HOST_DETAIL_SUCCESS_DELAY_SECONDS) { $env:FAPAI_HOST_DETAIL_SUCCESS_DELAY_SECONDS } else { '0' }" in script
    assert "$failureDelaySeconds = if ($env:FAPAI_HOST_DETAIL_FAILURE_DELAY_SECONDS) { $env:FAPAI_HOST_DETAIL_FAILURE_DELAY_SECONDS } else { '1' }" in script
    assert "'--success-delay-seconds', $successDelaySeconds" in script
    assert "'--failure-delay-seconds', $failureDelaySeconds" in script
    assert "'--active-loop-interval-seconds', $activeLoopIntervalSeconds" in script
    assert "'--loop-interval-seconds', '30'" in script
    assert "'--raw-only'" in script
    assert "'--manual-challenge-reporting'" in script
    assert "manual_captcha_report_v1" in script
    assert "$manualChallengeReportingSupported = $true" in script
    assert "$manualChallengeReportingSupported = $false" not in script
    assert "elseif ($manualChallengeReportingSupported)" in script
    assert "$apiStatusReachable -and" not in script
    assert "-not $manualChallengeReportingSupported -and" not in script
    assert "'--solver-enabled'" in script
    assert "$detailCdpEndpoint = if ($env:FAPAI_DETAIL_CDP_ENDPOINT)" in script
    assert "$solverEnabled = if ($env:FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED)" in script
    assert "-in @('1', 'true', 'yes', 'on')" in script


def test_pc2_host_direct_detail_worker_2_wraps_primary_direct_detail_worker() -> None:
    script = _pc2_host_script("start-host-direct-detail-worker-2.ps1")

    assert "FAPAI_HOST_DETAIL_WORKER_ID" in script
    assert "pc2-real-detail-2" in script
    assert "start-host-direct-detail-worker.ps1" in script


def test_pc2_host_direct_detail_worker_3_is_http_only() -> None:
    script = _pc2_host_script("start-host-direct-detail-worker-3.ps1")
    primary = _pc2_host_script("start-host-direct-detail-worker.ps1")

    assert "FAPAI_HOST_DETAIL_WORKER_ID" in script
    assert "pc2-real-detail-3" in script
    assert "detail_worker_3" in script
    assert "FAPAI_HOST_DETAIL_BROWSER_FALLBACK_OVERRIDE = '0'" in script
    assert "start-host-direct-detail-worker.ps1" in script
    assert "FAPAI_HOST_DETAIL_BROWSER_FALLBACK_OVERRIDE" in primary
    assert "SetEnvironmentVariable" in primary


def test_pc2_host_direct_analysis_worker_uses_small_retrying_batches_without_cdp() -> None:
    script = _pc2_host_script("start-host-direct-analysis-worker.ps1")

    assert "[string]$RequestedWorkerId = ''" in script
    assert "[string]$RequestedOutputDir = ''" in script
    assert "if ($RequestedWorkerId)" in script
    assert "if ($RequestedOutputDir)" in script
    assert "'[\"'']?(?=\\s|$)'" in script
    assert "load-host-direct-nas-env.ps1" in script
    assert "pc2-real-analysis-1" in script
    assert "output\\nodes\\pc2-real\\detail_analysis_worker" in script
    assert "FAPAI_HOST_ANALYSIS_TARGET_SUCCESS" in script
    assert "FAPAI_HOST_ANALYSIS_MAX_ATTEMPTS" in script
    assert "'--analysis-only'" in script
    assert "'--target-success', $targetSuccess" in script
    assert "'--max-attempts', $maxAttempts" in script
    assert "'2'" in script
    assert "'3'" in script
    assert "'--lease-seconds', '900'" in script
    assert "'--llm-preflight'" in script
    assert "OPENAI_API_KEY" in script
    assert "--cdp-endpoint" not in script


def test_pc2_host_direct_analysis_worker_2_uses_distinct_worker_and_output() -> None:
    script = _pc2_host_script("start-host-direct-analysis-worker-2.ps1")

    assert "FAPAI_HOST_ANALYSIS_WORKER_ID" in script
    assert "pc2-real-analysis-2" in script
    assert "FAPAI_HOST_ANALYSIS_OUTPUT_DIR" in script
    assert "detail_analysis_worker_2" in script
    assert "start-host-direct-analysis-worker.ps1" in script


def test_pc2_host_direct_analysis_worker_3_uses_distinct_worker_and_output() -> None:
    script = _pc2_host_script("start-host-direct-analysis-worker-3.ps1")

    assert "FAPAI_HOST_ANALYSIS_WORKER_ID" in script
    assert "pc2-real-analysis-3" in script
    assert "FAPAI_HOST_ANALYSIS_OUTPUT_DIR" in script
    assert "detail_analysis_worker_3" in script
    assert "start-host-direct-analysis-worker.ps1" in script


def test_pc2_analysis_env_import_is_allowlisted_backed_up_and_redacted() -> None:
    script = _pc2_host_script("import-host-direct-analysis-env.ps1")

    assert "load-host-direct-nas-env.ps1" in script
    assert "docker.local.env" in script
    assert "$allowedNames" in script
    assert "OPENAI_API_KEY" in script
    assert "OPENAI_MODEL_CANDIDATES" in script
    assert "OPENAI_REASONING_EFFORT" in script
    assert "analysis-enable-" in script
    assert "Copy-Item" in script
    assert "WriteAllLines" in script
    assert "$staleAllowedNames" in script
    assert "not $updates.ContainsKey($_)" in script
    assert "$lines.RemoveAt($index)" in script
    assert "removed_stale_setting_count" in script
    assert script.index("Copy-Item") < script.index("$lines.RemoveAt($index)")
    assert "source_within_approved_root" in script
    assert "openai_api_key_configured" in script
    assert "ConvertTo-Json -Compress" in script
    assert "Write-Output $value" not in script


def test_pc1_analysis_proxy_bridge_is_loopback_only_and_discovers_current_proxy() -> None:
    script = _script("start-pc1-analysis-proxy-bridge.ps1")

    assert "ProxyServer" in script
    assert "Get-NetTCPConnection" in script
    assert "127.0.0.1:{0}:[::1]:{1}" in script
    assert 'GetFolderPath("UserProfile")' in script
    assert 'GetFolderPath("LocalApplicationData")' in script
    assert "ExitOnForwardFailure=yes" in script
    assert "ServerAliveInterval=15" in script
    assert "Keep SSH in the foreground" in script
    assert "& $ssh @arguments" in script
    assert "remote_loopback_only = $true" not in script
    assert "RemotePassword" not in script


def test_pc1_analysis_proxy_bridge_task_restarts_on_logon() -> None:
    script = _script("register-pc1-analysis-proxy-bridge-task.ps1")

    assert "start-pc1-analysis-proxy-bridge.ps1" in script
    assert 'GetFolderPath("LocalApplicationData")' in script
    assert "Copy-Item" in script
    assert "New-ScheduledTaskAction" in script
    assert "New-ScheduledTaskTrigger -AtLogOn" in script
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in script
    assert "-RestartCount 999" in script
    assert "Register-ScheduledTask" in script


def test_pc2_host_direct_runbook_documents_worker_roles_and_auth_quiescing() -> None:
    runbook = REPO_ROOT.joinpath("docs", "runbooks", "pc2-host-direct-workers.md").read_text(encoding="utf-8")

    for worker_id in (
        "pc2-real-seed-1",
        "pc2-real-detail-1",
        "pc2-real-detail-2",
        "pc2-real-detail-3",
        "pc2-real-analysis-1",
        "pc2-real-analysis-2",
        "pc2-real-analysis-3",
    ):
        assert worker_id in runbook
    assert "import-host-direct-analysis-env.ps1" in runbook
    assert "FOR UPDATE SKIP LOCKED" in runbook
    assert "analysis worker" in runbook
    assert "PC1" in runbook
    assert "automatic solver remains enabled" in runbook


def test_pc2_host_direct_launch_script_runs_persistent_watchdog_with_detached_workers() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    assert "start-host-direct-seed-worker.ps1" in script
    assert "start-host-direct-detail-worker.ps1" in script
    assert "start-host-direct-detail-worker-2.ps1" in script
    assert "start-host-direct-detail-worker-3.ps1" in script
    assert "start-host-direct-analysis-worker.ps1" in script
    assert "start-host-direct-analysis-worker-2.ps1" in script
    assert "start-host-direct-analysis-worker-3.ps1" in script
    assert "pc2-real-seed-1" in script
    assert "pc2-real-detail-1" in script
    assert "pc2-real-detail-2" in script
    assert "pc2-real-detail-3" in script
    assert "pc2-real-analysis-1" in script
    assert "pc2-real-analysis-2" in script
    assert "pc2-real-analysis-3" in script
    assert "Invoke-CimMethod" in script
    assert "Win32_Process" in script
    assert "MethodName Create" in script
    assert "cmd.exe /d /c powershell.exe -WindowStyle Hidden -NonInteractive" in script
    assert "logs\\codex-pc2-real" in script
    assert "seed_collector_summary.json" in script
    assert "detail_worker_summary.json" in script
    assert "LastWriteTime" in script
    assert "summary stale" in script
    assert "duplicate worker root" in script
    assert "Stop-WorkerProcessTree" in script
    assert "Get-CimInstance Win32_Process" in script
    assert "ParentProcessId" in script
    assert "Global\\FapaiFangPc2RealWorkers" in script
    assert "workerMutex.WaitOne(0)" in script
    assert "while ($true)" in script
    assert "Start-Sleep -Seconds $PollSeconds" in script
    assert "Start-Process" not in script


def test_pc2_host_watchdog_scales_detail_and_analysis_workers_with_bounded_counts() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    assert "[int]$DetailWorkerCount = 0" in script
    assert "[int]$AnalysisWorkerCount = 0" in script
    assert "function Resolve-WorkerCount" in script
    assert "FAPAI_HOST_DETAIL_WORKER_COUNT" in script
    assert "FAPAI_HOST_ANALYSIS_WORKER_COUNT" in script
    assert script.count("-DefaultCount 4") == 2
    assert "$resolved -lt 3 -or $resolved -gt 8" in script
    assert "for ($index = 4; $index -le $DetailWorkerCount; $index++)" in script
    assert "for ($index = 4; $index -le $AnalysisWorkerCount; $index++)" in script
    assert '"pc2-real-detail-$index"' in script
    assert '"pc2-real-analysis-$index"' in script
    assert "'-BrowserFallbackOverride', '0'" in script
    assert "ScriptArguments = @(" in script
    assert "$quoteNativeArgument" in script
    assert "$scriptPathText" in script
    assert "$stdoutPathText" in script
    assert "$stderrPathText" in script
    assert "'[\"'']?(?=\\s|$)'" in script


def test_pc2_local_solver_launcher_uses_only_local_9223() -> None:
    script = _pc2_host_script("start-pc2-local-solver.ps1")

    assert "http://127.0.0.1:9223" in script
    assert "--cdp-endpoint $CdpEndpoint" in script
    assert "FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED" in script
    assert "FAPAI_SOLVER_COOLDOWN_FAIL_THRESHOLD = '10'" in script
    assert "FAPAI_SOLVER_COOLDOWN_SECONDS = '180'" in script
    assert "FAPAI_SLIDER_RETRY_INTERVAL_SECONDS = '5'" in script
    assert "FAPAI_LOCAL_SOLVER_POLL_SECONDS = '5'" in script
    assert "env.worker.local" in script
    assert "9225" not in script
