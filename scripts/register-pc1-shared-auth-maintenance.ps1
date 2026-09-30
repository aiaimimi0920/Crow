param(
    [string]$DataRoot = "",
    [string]$AlertWebhookUrl = "",
    [int]$Port = 9225,
    [int]$WatchdogWaitSeconds = 180,
    [int]$WatchdogPollSeconds = 5,
    [int]$RecoveryMonitorIntervalMinutes = 1,
    [int]$RecentMinutes = 3,
    [int]$MinRecentSeedItems = 1,
    [int]$StaleSeedMinutes = 3,
    [int]$MissingPayloadThreshold = 20,
    [int]$RecoveryCooldownMinutes = 10,
    [int]$ManualAuthGraceMinutes = 30,
    [string]$ApiBase = "",
    [string]$ApiCaFile = "",
    [int]$NasRecoveryIntervalMinutes = 1,
    [int]$LoginWindowSeconds = 300,
    [string]$ProfileDir = "",
    [string]$BrowserPath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    [int]$NasRecoveryExecutionTimeLimitMinutes = 10,
    [string]$TaskPath = "\FapaiFang\",
    [switch]$UseSystemProxy,
    [switch]$StartWatchdogNow
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")
if (-not $ProfileDir) { $ProfileDir = Join-Path (Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot) "chrome-cdp-profile-pc1-human-clean" }
. (Join-Path $PSScriptRoot "collection-api-origin.ps1")
if (-not $ApiBase) {
    $ApiBase = if ($env:FAPAI_COLLECTOR_API_BASE) { $env:FAPAI_COLLECTOR_API_BASE } else { $env:FAPAI_API_BASE_URL }
}
$ApiBase = (ConvertTo-CollectionApiOrigin $ApiBase) + "/api"
if (-not $ApiCaFile) { $ApiCaFile = $env:FAPAI_API_CA_FILE }
if ($ApiCaFile -and -not (Test-Path -LiteralPath $ApiCaFile -PathType Leaf)) {
    throw "Collection API CA file is unavailable."
}

function Resolve-DefaultDataRoot {
    return Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot
}

$resolvedDataRoot = Resolve-DefaultDataRoot
$outputPath = Join-Path $resolvedDataRoot "secrets\nodes\pc2\taobao-cookies.json"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$registerWatchdogScript = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\register-taobao-login-watchdog-task.ps1"))
$registerNasRecoveryScript = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\register-pc1-nas-auth-recovery-task.ps1"))

foreach ($required in @($registerWatchdogScript, $registerNasRecoveryScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing shared-auth maintenance helper: $required"
    }
}

$watchdogArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $registerWatchdogScript,
    "-DataRoot", $resolvedDataRoot,
    "-OutputPath", $outputPath,
    "-Port", $Port,
    "-WaitSeconds", $WatchdogWaitSeconds,
    "-PollSeconds", $WatchdogPollSeconds,
    "-TaskPath", $TaskPath
)
if ($AlertWebhookUrl) {
    $watchdogArgs += @("-AlertWebhookUrl", $AlertWebhookUrl)
}
if ($UseSystemProxy) {
    $watchdogArgs += "-UseSystemProxy"
}

$nasRecoveryArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $registerNasRecoveryScript,
    "-ApiBase", $ApiBase,
    "-DataRoot", $resolvedDataRoot,
    "-OutputPath", $outputPath,
    "-Port", $Port,
    "-IntervalMinutes", $NasRecoveryIntervalMinutes,
    "-LoginWindowSeconds", $LoginWindowSeconds,
    "-ProfileDir", $ProfileDir,
    "-BrowserPath", $BrowserPath,
    "-ExecutionTimeLimitMinutes", $NasRecoveryExecutionTimeLimitMinutes,
    "-TaskPath", $TaskPath
)
if ($UseSystemProxy) {
    $nasRecoveryArgs += "-UseSystemProxy"
}
if ($ApiCaFile) {
    $nasRecoveryArgs += @("-ApiCaFile", $ApiCaFile)
}

& powershell.exe @watchdogArgs | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Watchdog task registration failed with exit code $LASTEXITCODE."
}

& powershell.exe @nasRecoveryArgs | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "NAS auth recovery task registration failed with exit code $LASTEXITCODE."
}

Enable-ScheduledTask -TaskName "FapaiFangTaobaoLoginWatchdog" -TaskPath $TaskPath | Out-Null
Enable-ScheduledTask -TaskName "FapaiFangNasAuthRecovery" -TaskPath $TaskPath | Out-Null
$legacyRecovery = Get-ScheduledTask -TaskName "FapaiFangTaobaoLoginRecoveryMonitor" -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($legacyRecovery) {
    Disable-ScheduledTask -TaskName "FapaiFangTaobaoLoginRecoveryMonitor" -TaskPath $TaskPath | Out-Null
}

if ($StartWatchdogNow) {
    Start-ScheduledTask -TaskName "FapaiFangTaobaoLoginWatchdog" -TaskPath $TaskPath
}

$watchdogTask = Get-ScheduledTask -TaskName "FapaiFangTaobaoLoginWatchdog" -TaskPath $TaskPath
$watchdogInfo = Get-ScheduledTaskInfo -TaskName "FapaiFangTaobaoLoginWatchdog" -TaskPath $TaskPath
$recoveryTask = Get-ScheduledTask -TaskName "FapaiFangNasAuthRecovery" -TaskPath $TaskPath
$recoveryInfo = Get-ScheduledTaskInfo -TaskName "FapaiFangNasAuthRecovery" -TaskPath $TaskPath

[pscustomobject]@{
    data_root = $resolvedDataRoot
    port = $Port
    use_system_proxy = [bool]$UseSystemProxy
    start_watchdog_now = [bool]$StartWatchdogNow
    watchdog = [pscustomobject]@{
        task_name = $watchdogTask.TaskName
        task_path = $watchdogTask.TaskPath
        state = [string]$watchdogTask.State
        last_run_time = $watchdogInfo.LastRunTime
        last_task_result = $watchdogInfo.LastTaskResult
    }
    nas_auth_recovery = [pscustomobject]@{
        task_name = $recoveryTask.TaskName
        task_path = $recoveryTask.TaskPath
        state = [string]$recoveryTask.State
        last_run_time = $recoveryInfo.LastRunTime
        last_task_result = $recoveryInfo.LastTaskResult
    }
    thresholds = [pscustomobject]@{
        recent_minutes = $RecentMinutes
        min_recent_seed_items = $MinRecentSeedItems
        stale_seed_minutes = $StaleSeedMinutes
        missing_payload_threshold = $MissingPayloadThreshold
        recovery_cooldown_minutes = $RecoveryCooldownMinutes
        manual_auth_grace_minutes = $ManualAuthGraceMinutes
        nas_recovery_interval_minutes = $NasRecoveryIntervalMinutes
        login_window_seconds = $LoginWindowSeconds
    }
} | ConvertTo-Json -Compress
