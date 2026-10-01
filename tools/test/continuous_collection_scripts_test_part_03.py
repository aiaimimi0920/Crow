from __future__ import annotations

from tools.test.continuous_collection_scripts_test_context import *


def test_pc2_local_solver_cmd_launcher_enables_automatic_os_mouse_solver() -> None:
    script = _pc2_host_script("start-pc2-local-solver.cmd")

    assert "FAPAI_CDP_ENDPOINT=http://127.0.0.1:9223" in script
    assert "FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED=1" in script
    assert "FAPAI_SOLVER_OS_MOUSE=1" in script
    assert "FAPAI_SOLVER_COOLDOWN_FAIL_THRESHOLD=10" in script
    assert "FAPAI_SOLVER_COOLDOWN_SECONDS=180" in script
    assert "FAPAI_SLIDER_RETRY_INTERVAL_SECONDS=5" in script
    assert "FAPAI_LOCAL_SOLVER_POLL_SECONDS=5" in script
    assert "pc2_local_solver.py" in script


def test_pc2_report_cdp_forwarder_targets_solver_port_9223() -> None:
    script = _pc2_host_script("configure-pc2-report-cdp-forwarder.ps1")

    assert "[int]$ReportPort = 9224" in script
    assert "[int]$TargetPort = 9223" in script
    assert "netsh.exe interface portproxy" in script
    assert "Test-NetConnection $TargetAddress -Port $TargetPort" in script
    assert "9225" not in script


def test_pc2_host_watchdog_cools_down_analysis_workers_when_llm_backend_is_unavailable() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    assert "[int]$AnalysisBackendRetryCooldownSeconds = 900" in script
    assert "$analysisBackendRetryAt = @{}" in script
    assert "$analysisUnavailableSummaryWriteTicks = @{}" in script
    assert "IsAnalysis = $true" in script
    assert "IsAnalysis = $false" in script
    assert "function Get-WorkerSummaryState" in script
    assert "ConvertFrom-Json" in script
    assert "detail_worker_llm_unavailable" in script
    assert "function Initialize-AnalysisUnavailableSummaryBaseline" in script
    assert "Initialize-AnalysisUnavailableSummaryBaseline" in script
    assert "function Test-NewAnalysisBackendUnavailableSummary" in script
    assert "function Enter-AnalysisBackendCooldown" in script
    assert "function Test-AnalysisBackendCooldown" in script
    assert "analysis backend unavailable" in script
    assert "analysis backend cooldown expired" in script
    ensure_start = script.index("function Ensure-Worker")
    ensure_end = script.index("Write-WatchdogLog 'pc2 worker watchdog booted'", ensure_start)
    ensure_block = script[ensure_start:ensure_end]
    assert ensure_block.index("Test-NewAnalysisBackendUnavailableSummary") < ensure_block.index(
        "Get-ProcessAgeSeconds"
    )
    assert "Stop-WorkerProcessTree" in ensure_block
    assert "Enter-AnalysisBackendCooldown" in ensure_block
    assert "Test-AnalysisBackendCooldown" in ensure_block
    boot_index = script.index("Write-WatchdogLog 'pc2 worker watchdog booted'")
    baseline_call_index = script.index("Initialize-AnalysisUnavailableSummaryBaseline", boot_index)
    loop_index = script.index("while ($true)", baseline_call_index)
    assert boot_index < baseline_call_index < loop_index


def test_pc2_host_watchdog_recovers_unreachable_cdp_with_bounded_retries() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    assert "[int]$CdpFailureThreshold = 3" in script
    assert "[int]$CdpRestartCooldownSeconds = 300" in script
    assert "function Test-CdpEndpoint" in script
    assert "[System.Net.HttpWebRequest]::Create" in script
    assert "$request.Proxy = $null" in script
    assert "function Ensure-CdpBrowser" in script
    assert "$consecutiveCdpFailures" in script
    assert "$lastCdpRestartAt" in script
    assert "start-taobao-cdp-browser.ps1" in script
    assert "http://127.0.0.1:9223" in script
    assert "edge-cdp-profile-pc2" in script
    assert "'-UseSystemProxy'" in script
    assert "'-DisableExtensions'" in script
    assert "'-StartMinimized'" in script
    assert "'-EnsureOnly'" in script
    assert "'-CdpStartupTimeoutSeconds', '120'" in script
    assert "'about:blank'" in script
    assert "cdp recovery started" in script


def test_pc2_host_watchdog_only_gates_cdp_dependent_workers_on_cdp_health() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    assert "$cdpRequired = @($workerSpecs | Where-Object { $_.RequiresCdp }).Count -gt 0" in script
    assert "$cdpReady = -not $cdpRequired" in script
    assert "$cdpReady = Ensure-CdpBrowser" in script
    assert "RequiresCdp = $collectorRequiresCdp" in script
    assert "RequiresCdp = $false" in script
    assert "$spec.RequiresCdp -and -not $cdpReady" in script
    assert "cdp unavailable; skipping CDP-dependent worker supervision" in script
    assert "if (-not $spec.RequiresCdp)" in script


def test_pc2_external_cookie_snapshot_mode_keeps_collectors_and_analysis_independent_of_cdp() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    ensure_start = script.index("function Ensure-CdpBrowser")
    ensure_end = script.index("function Get-WorkerProcesses", ensure_start)
    ensure_block = script[ensure_start:ensure_end]
    assert "if ($externalCdp)" in ensure_block
    assert "Stop-WorkersForCdpRecovery" in ensure_block
    assert "$collectorRequiresCdp = -not ($externalCdp -and $cookieSnapshotPreferred)" in script

    analysis_start = script.index("Name = 'analysis-1'")
    analysis_end = script.index("},", analysis_start)
    assert "RequiresCdp = $false" in script[analysis_start:analysis_end]

    analysis_2_start = script.index("Name = 'analysis-2'")
    analysis_2_end = script.index("},", analysis_2_start)
    assert "RequiresCdp = $false" in script[analysis_2_start:analysis_2_end]

    analysis_3_start = script.index("Name = 'analysis-3'")
    analysis_3_end = script.index("},", analysis_3_start)
    assert "RequiresCdp = $false" in script[analysis_3_start:analysis_3_end]

    seed_start = script.index("Name = 'seed'")
    seed_end = script.index("},", seed_start)
    assert "RequiresCdp = $collectorRequiresCdp" in script[seed_start:seed_end]
    assert "StopsWhenCollectionPaused = $false" in script[seed_start:seed_end]

    detail3_start = script.index("Name = 'detail-3-http'")
    detail3_end = script.index("}", detail3_start)
    assert "RequiresCdp = $collectorRequiresCdp" in script[detail3_start:detail3_end]
    assert "StopsWhenCollectionPaused = $true" in script[detail3_start:detail3_end]


def test_pc2_collection_pause_keeps_scope_aware_seed_and_analysis_supervised() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")

    assert "function Test-CollectionPaused" in script
    assert "function Get-CollectionPauseState" in script
    assert 'Invoke-RestMethod -Uri "$apiBaseUrl/status"' in script
    assert "function Stop-WorkersForCollectionPause" in script
    assert 'Reason "collection paused"' in script
    assert "$seedCollectionPaused" in script
    assert "$detailCollectionPaused" in script
    assert "Stop-WorkersForCollectionPause" in script
    assert "if (-not $spec.StopsWhenCollectionPaused)" in script
    assert "$scopePaused -and $spec.StopsWhenCollectionPaused" in script


def test_pc2_collection_pause_check_fails_closed_when_nas_status_is_unavailable() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")
    function_start = script.index("function Test-CollectionPaused")
    function_end = script.index("function Start-CdpRecovery", function_start)
    function_body = script[function_start:function_end]

    assert "catch {" in function_body
    assert "return $true" in function_body
    assert "return $false" not in function_body


def test_pc2_host_watchdog_stops_workers_before_restarting_cdp() -> None:
    script = _pc2_host_script("launch-host-direct-workers.ps1")
    recovery_start = script.index("function Start-CdpRecovery")
    recovery_end = script.index("function Ensure-CdpBrowser", recovery_start)
    recovery_block = script[recovery_start:recovery_end]

    assert "Stop-WorkersForCdpRecovery" in recovery_block
    assert recovery_block.index("Stop-WorkersForCdpRecovery") < recovery_block.index("& powershell.exe @arguments")
    assert "function Stop-WorkersForCdpRecovery" in script
    assert "Stop-WorkerProcessTree" in script
    assert 'Reason "cdp recovery"' in script


def test_pc2_host_watchdog_task_registration_has_no_runtime_limit_and_restarts() -> None:
    script = _pc2_host_script("register-host-direct-worker-watchdog.ps1")

    assert "launch-host-direct-workers.ps1" in script
    assert "New-ScheduledTaskAction" in script
    assert "'-WindowStyle', 'Hidden'" in script
    assert "New-ScheduledTaskTrigger" in script
    assert "-AtLogOn" in script
    assert "New-ScheduledTaskPrincipal" in script
    assert "-LogonType Interactive" in script
    assert "New-ScheduledTaskSettingsSet" in script
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in script
    assert "-RestartCount 999" in script
    assert "-RestartInterval (New-TimeSpan -Minutes 1)" in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "Register-ScheduledTask" in script
    assert "Start-ScheduledTask" in script
    assert "Unregister-ScheduledTask" in script
    assert "FPF-HostSeedWorker-Logon" in script
    assert "FPF-HostDetailWorker-Logon" in script
    assert "FapaifangPc2RealSeed" in script
    assert "FapaifangPc2RealDetail1" in script
    assert "FapaifangPc2RealDetail2" in script
    assert "FPF-HostCDP-Logon" in script
    assert "FPF-Launch-CDP-Interactive" in script
    assert "FapaiFangPc2CdpInteractive" in script
    assert "FapaiFangPc2HiddenCdpSvc2" in script
    assert "FapaiFangTaobaoCdpBrowser" in script
    assert "FapaiFangTaobaoLoginWatchdog" in script
    assert "$legacyTasks = @(Get-ScheduledTask -TaskName $legacyTaskName" in script
    assert "-TaskPath $legacyTask.TaskPath" in script


def test_pc2_host_open_auth_latest_uses_live_status_and_sanitizes_punish_targets() -> None:
    script = _pc2_host_script("open-auth-latest.ps1")

    assert script.lstrip("\ufeff\r\n ").startswith("param(")
    assert script.index("param(") < script.index("$ErrorActionPreference")
    assert "[string]$RequestedUrl = ''" in script
    assert "[switch]$ResetToBlank" in script
    assert "'about:blank'" in script
    assert "$rawTargetUrl = if ($ResetToBlank)" in script
    assert "} elseif ($RequestedUrl) {" in script
    assert "Invoke-WebRequest -Uri \"$($ApiBaseUrl.TrimEnd('/'))/status\"" in script
    assert "captcha_solver" in script
    assert "last_request" in script
    assert script.index("$lastRequest.challenge_target_url") < script.index(
        "$lastRequest.target_url"
    )
    assert "function Build-DetailUrl" in script
    assert "'^/sf_item/[0-9]+\\.htm$'" in script
    assert "$targetHost -eq 'sf-item.taobao.com'" in script
    assert "_____tmd_____/punish" in script
    assert "x5secdata" in script
    assert "__captcha_solver_bg=1" in script
    assert "start-taobao-cdp-browser.ps1" in script
    assert "$defaultUrl = 'https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1'" in script
    assert "-UseSystemProxy" in script
    assert "-DisableExtensions" in script
    assert "-ForceNew" in script
    assert "-CdpStartupTimeoutSeconds 120" in script


def test_pc2_cdp_self_heal_recovers_browser_before_resetting_matching_challenge() -> None:
    script = _pc2_host_script("watch-pc2-cdp-self-heal.ps1")

    assert "[int]$PollSeconds = 60" in script
    assert "[int]$CdpFailureThreshold = 3" in script
    assert "[int]$StaleChallengeSeconds = 300" in script
    assert "[int]$RestartCooldownSeconds = 180" in script
    assert "[int]$SolverAttemptThreshold = 10" in script
    assert "[int]$SolverProgressGraceSeconds = 180" in script
    assert "[int]$CdpRecoveryTimeoutSeconds = 240" in script
    assert "/json/version" in script
    assert "/json/list" in script
    assert "CDP has no usable page targets" in script
    assert "about:blank|edge:|chrome:|devtools:" in script
    assert "challenge_page_count" in script
    assert "login_page_count" in script
    assert "$manualLoginDeferred" in script
    assert "stale_recovery_deferred_for_manual_login" in script
    assert "-ResetToBlank" in script
    assert "Test-CdpRuntime -AllowBlankPage:$safeReset" in script
    assert "$cdp = Test-CdpRuntime -AllowBlankPage" in script
    assert "CDP safe reset still exposes challenge page targets" in script
    assert "CDP challenge page reappeared immediately after runtime restart" in script
    assert "auth_complete_pending" in script
    assert "-Name 'manual_only' -DefaultValue $true) -ne $true" in script
    assert "$stalePc2Challenge" in script
    assert "$stalePc2ChallengeCandidate" in script
    assert "$staleChallengeDeferred" in script
    assert "function Get-SolverChallengeActivity" in script
    assert "slider_attempt_started_at" in script
    assert "slider_last_progress_at" in script
    assert "stale_recovery_deferred_for_solver" in script
    assert "'cdp_unhealthy'" in script
    assert "'stale_pc2_challenge'" in script
    assert "function Get-PropertyValue" in script
    assert "if ($parsed -is [System.Array])" in script
    assert "Write-Output $item" in script
    assert "if ($challengeId -and $ResetMatchingChallenge)" in script
    assert "Stop-ScheduledTask -TaskName $taskName" in script
    assert "function Get-RecoveryRoleProcess" in script
    assert "$scheduledDeadline = (Get-Date).AddSeconds(20)" in script
    assert "$null -eq (Get-RecoveryRoleProcess -Role $role)" in script
    assert "$taskIsRunning" in script
    assert "-and -not $taskIsRunning" in script
    assert "Start-Process" in script
    assert "launch_modes" in script
    assert "runtime process did not remain running" in script
    assert "Enable-ScheduledTask" not in script
    assert "launch-host-direct-workers\\.ps1|start-pc2-local-solver\\.ps1" in script
    assert script.index("Stop-Process -Id $process.ProcessId") < script.index(
        "Stop-ScheduledTask -TaskName $taskName"
    )
    assert "open-auth-latest.ps1" in script
    assert "/collection/auth/resume_after_cooldown" in script
    assert "resume_request_id" in script
    assert "challenge_id = $ChallengeId" in script
    assert "/collection/control/resume" not in script
    assert script.index("Test-CdpRuntime") < script.index("Invoke-ChallengeReset")
    assert script.index("Invoke-ChallengeReset -ChallengeId") < script.index(
        "Remove-Item -LiteralPath $solverFallbackPath"
    )
    assert "Start-RecoveryTasks" in script
    assert "solver_task_state" in script
    assert "worker_task_state" in script
    assert "runtime_restart_failed" in script
    assert "Test-RecoveryTasksRunning" in script
    assert "runtime_restored_during_cooldown" in script
    assert "FapaiPc2CdpSelfHeal" in script
    recovery = script[
        script.index("function Invoke-CdpRecovery") : script.index("function Invoke-SelfHealCheck")
    ]
    assert "} finally {" not in recovery
    assert recovery.index("Invoke-ChallengeReset -ChallengeId") < recovery.index(
        "$taskStatus = Start-RecoveryTasks"
    )
    assert "NAS challenge marker remained active after matching reset" in recovery
    assert "CDP became unhealthy immediately after task restart" in recovery
    assert "recovery_runtime_stopped" in recovery
    assert "recovery_browser_restarted" in recovery
    assert "recovery_cdp_ready" in recovery
    assert "recovery_challenge_reset_confirmed" in recovery
    assert "recovery_runtime_restarted" in recovery
    self_heal_check = script[
        script.index("function Invoke-SelfHealCheck") : script.index("$mutex =")
    ]
    assert "$recoveryError = $_.Exception.Message" in self_heal_check
    assert "if (-not $runtimeRestored)" in self_heal_check
    assert "$rollbackStatus = Start-RecoveryTasks" in self_heal_check
    assert "recovery_runtime_rollback_succeeded" in self_heal_check
    assert "recovery_runtime_rollback_failed" in self_heal_check
    assert "runtime_restored = $runtimeRestored" in self_heal_check


def test_pc2_cdp_self_heal_task_runs_hidden_in_interactive_session_and_restarts() -> None:
    script = _pc2_host_script("register-pc2-cdp-self-heal.ps1")

    assert "FapaiPc2CdpSelfHeal" in script
    assert "watch-pc2-cdp-self-heal.ps1" in script
    assert "'-WindowStyle', 'Hidden'" in script
    assert "'-PollSeconds', '60'" in script
    assert "'-CdpFailureThreshold', '3'" in script
    assert "'-StaleChallengeSeconds', '300'" in script
    assert "'-RestartCooldownSeconds', '180'" in script
    assert "'-SolverAttemptThreshold', '10'" in script
    assert "'-SolverProgressGraceSeconds', '180'" in script
    assert "'-CdpRecoveryTimeoutSeconds', '240'" in script
    assert "New-ScheduledTaskTrigger -AtLogOn" in script
    assert "New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(30)" in script
    assert "-LogonType Interactive" in script
    assert "-RunLevel Highest" in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in script
    assert "-RestartCount 999" in script
    assert "-RestartInterval (New-TimeSpan -Minutes 1)" in script
    assert "Register-ScheduledTask" in script
    assert "Start-ScheduledTask" not in script
    assert "watch-pc2-cdp-self-heal\\.ps1" in script
    assert "taskkill.exe /PID $process.ProcessId /T /F" in script
    assert "Stop-Process -Id $process.ProcessId" in script
    assert "start-scheduled-task-in-active-session.ps1" in script
    assert "register-pc2-cdp-self-heal-bootstrap.ps1" in script
    assert "& $bootstrapRegister" in script


def test_pc2_active_session_starter_uses_console_token_without_password() -> None:
    script = _pc2_host_script("start-scheduled-task-in-active-session.ps1")

    assert "WTSGetActiveConsoleSessionId" in script
    assert "WTSQueryUserToken" in script
    assert "Get-Process -Name explorer" in script
    assert "OpenProcessToken" in script
    assert "DuplicateTokenEx" in script
    assert "0x02000000" in script
    duplicate_call = script[script.index("::DuplicateTokenEx(") : script.index("Assert-Win32Result -Succeeded $duplicatedToken")]
    assert "2,1,[ref]$primaryToken" in "".join(duplicate_call.split())
    create_call = script[script.index("::CreateProcessWithTokenW(") :]
    assert "$primaryToken,0,$powerShellPath" in "".join(create_call.split())
    assert "CreateProcessWithTokenW" in script
    assert "CreateProcessAsUserW" in script
    assert "CreateEnvironmentBlock" in script
    assert "DestroyEnvironmentBlock" in script
    assert "[IntPtr]::Zero" in script
    assert "[switch]$Supervise" in script
    assert "function Get-WatchdogLatestActivity" in script
    assert "function Wait-WatchdogProcess" in script
    assert "watchdog_unresponsive" in script
    assert "MaxSilenceSeconds = 300" in script
    assert "taskkill.exe /PID $ProcessId /T /F" in script
    assert "Wait-WatchdogProcess -ProcessId $bootstrapResult.process_id" in script
    assert "cdp-self-heal-bootstrap.log" in script
    assert "bootstrap_failed" in script
    assert "winsta0\\default" in script
    assert "function Get-TaskActionDefinition" in script
    assert "New-Object -ComObject 'Schedule.Service'" in script
    assert "$service.GetFolder($Path)" in script
    assert "$folder.GetTask($Name)" in script
    assert "$actions.Item(1)" in script
    assert "Get-ScheduledTask" not in script
    assert "Start-Process -FilePath '$escapedActionExecute'" in script
    assert "'ProcessRunning'" in script
    assert "watch-pc2-cdp-self-heal\\.ps1" in script
    assert "interactive-task-bootstrap-" in script
    assert "Password" not in script


def test_pc2_self_heal_bootstrap_repeats_as_system_without_password() -> None:
    script = _pc2_host_script("register-pc2-cdp-self-heal-bootstrap.ps1")

    assert "FapaiPc2CdpSelfHealBootstrap" in script
    assert "start-scheduled-task-in-active-session.ps1" in script
    assert "-RepetitionInterval (New-TimeSpan -Minutes 1)" in script
    assert "-RepetitionDuration (New-TimeSpan -Days 3650)" in script
    assert "'-Supervise'" in script
    assert "'-TaskPath'" not in script
    assert "-UserId 'SYSTEM'" in script
    assert "-LogonType ServiceAccount" in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in script
    assert "Register-ScheduledTask" in script
    assert "Start-ScheduledTask" in script
    assert "Password" not in script


def test_pc2_host_open_auth_latest_resets_login_redirect_targets_to_default_list() -> None:
    script = _pc2_host_script("open-auth-latest.ps1")

    assert "$targetHost.Contains('login.taobao.com')" in script
    assert "$lowerPath.Contains('havanaone/login')" in script
    assert "return $defaultUrl" in script
