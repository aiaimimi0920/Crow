param(
    [string]$DataRoot = "",
    [string]$ApiBaseUrl = "",
    [string]$AlertWebhookUrl = "",
    [int]$RecentMinutes = 3,
    [int]$MinRecentSeedItems = 1,
    [int]$StaleSeedMinutes = 3,
    [int]$MissingPayloadThreshold = 20,
    [int]$RecoveryCooldownMinutes = 10,
    [int]$ManualAuthGraceMinutes = 30,
    [string]$TaskName = "FapaiFangTaobaoLoginWatchdog",
    [string]$TaskPath = "\FapaiFang\",
    [string]$PostgresContainer = "fapaifang-postgres",
    [string]$DbUser = "fapaifang",
    [string]$DbName = "fapaifang",
    [string]$StatePath = "",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot 'project-environment.ps1')



. (Join-Path $PSScriptRoot "project-data-root.ps1")
$DataRoot = Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot
$resolvedAlertWebhookUrl = if ($AlertWebhookUrl) { $AlertWebhookUrl } else { [string](Get-CrowEnvironmentValue -Name 'CROW_OPERATIONS_WEBHOOK_URL') }

$moduleRoot = Join-Path $PSScriptRoot "trigger-taobao-login-recovery-if-needed"
. (Join-Path $moduleRoot "state-and-alert.ps1")
. (Join-Path $moduleRoot "signal-sources.ps1")

if ($RecentMinutes -lt 1) {
    throw "RecentMinutes must be at least 1."
}
if ($MinRecentSeedItems -lt 0) {
    throw "MinRecentSeedItems must not be negative."
}
if ($StaleSeedMinutes -lt 1) {
    throw "StaleSeedMinutes must be at least 1."
}
if ($MissingPayloadThreshold -lt 1) {
    throw "MissingPayloadThreshold must be at least 1."
}
if ($RecoveryCooldownMinutes -lt 1) {
    throw "RecoveryCooldownMinutes must be at least 1."
}
if ($ManualAuthGraceMinutes -lt 0) {
    throw "ManualAuthGraceMinutes must not be negative."
}

if (-not $StatePath) {
    $StatePath = Join-Path $DataRoot "runtime\taobao-login-recovery-monitor-state.json"
}

$usePostgresSignals = $false
try {
    $containerNames = @(& docker ps -a --format "{{.Names}}" 2>$null)
    if ($LASTEXITCODE -eq 0 -and ($containerNames -contains $PostgresContainer)) {
        $usePostgresSignals = $true
    }
} catch {
    $usePostgresSignals = $false
}

$signal = if ($usePostgresSignals) {
    Get-PostgresSignalSnapshot
} else {
    Get-SeedSummarySignalSnapshot
}

$recentSeedItems = $signal.recent_seed_items
$recentOccurrences = $signal.recent_occurrences
$retryableErrors = $signal.retryable_error_count
$latestSeedAgeMinutes = $signal.latest_seed_age_minutes
$challengePressure = (
    [string]$signal.summary_last_reason -match "punish|captcha|challenge" -or
    [string]$signal.summary_last_decision -eq "seed_page_retryable_failure"
)
$seedStalled = (
    ($recentSeedItems -lt $MinRecentSeedItems) -and
    (($latestSeedAgeMinutes -ge $StaleSeedMinutes) -or $challengePressure)
)
$errorPressure = (($retryableErrors -ge $MissingPayloadThreshold) -or $challengePressure)
$shouldTrigger = ($seedStalled -and $errorPressure)

$snapshot = [ordered]@{
    signal_source = $signal.signal_source
    recent_minutes = $RecentMinutes
    recent_seed_items = $recentSeedItems
    recent_occurrences = $recentOccurrences
    retryable_error_count = $retryableErrors
    latest_seed_age_minutes = $latestSeedAgeMinutes
    min_recent_seed_items = $MinRecentSeedItems
    stale_seed_minutes = $StaleSeedMinutes
    missing_payload_threshold = $MissingPayloadThreshold
    seed_stalled = $seedStalled
    error_pressure = $errorPressure
    should_trigger = $shouldTrigger
    collection_paused = $signal.collection_paused
    summary_last_reason = $signal.summary_last_reason
    summary_last_decision = $signal.summary_last_decision
    api_status_reached = $signal.api_status_reached
}
if ($signal.Contains("summary_path")) {
    $snapshot.summary_path = $signal.summary_path
}

# Manual auth escalation is the primary PC1 fallback signal from PC2's local solver.
# Resolve it before the generic pause guard so an auth pause can start the on-demand
# visible watchdog instead of being mistaken for an already-handled operator pause.
$apiBaseResolvedForManualCheck = Resolve-ApiBaseUrl -Value $ApiBaseUrl
$manualAuthRequired = $false
$manualSolverSnapshot = $null
try {
    $apiStatusForManualCheck = Invoke-RestMethod -Uri "$apiBaseResolvedForManualCheck/status" -TimeoutSec 5
    if ($null -ne $apiStatusForManualCheck) {
        $manualSolverSnapshot = $apiStatusForManualCheck.captcha_solver
        $manualAuthRequired = ([bool]$manualSolverSnapshot.manual_required -or [bool]$manualSolverSnapshot.force_unlock_flag_exists)
    }
} catch {
    $manualAuthRequired = $false
}
$snapshot | Add-Member -NotePropertyName manual_auth_required -NotePropertyValue $manualAuthRequired
$snapshot | Add-Member -NotePropertyName manual_solver_status -NotePropertyValue $manualSolverSnapshot -Force

if ($snapshot.collection_paused -eq $true -and -not $manualAuthRequired) {
    Clear-ManualAuthObservation -Path $StatePath
    $closedBrowserCount = Stop-DedicatedRecoveryBrowser
    Send-OperationalAlert -EventName "collection_paused_for_auth" -Payload @{
        snapshot = $snapshot
        task_name = $TaskName
        task_path = $TaskPath
    }
    Write-JsonLine ([ordered]@{
        status = "collection_paused"
        snapshot = $snapshot
        closed_recovery_browser_count = $closedBrowserCount
        note = "Collection is already paused for auth recovery. This script will not start another watchdog instance."
    })
    exit 0
}

if ($manualAuthRequired -and $snapshot.signal_source -eq "postgres_container") {
    try {
        $apiStatusRefresh = Invoke-RestMethod -Uri "$apiBaseResolvedForManualCheck/status" -TimeoutSec 5
        if ($null -ne $apiStatusRefresh) {
            $snapshot.collection_paused = $apiStatusRefresh.paused -eq $true
        }
    } catch {
    }
}

if ($manualAuthRequired) {
    $manualOnly = [bool]$manualSolverSnapshot.manual_only
    if (-not $manualOnly) {
        Clear-ManualAuthObservation -Path $StatePath
        $closedBrowserCount = Stop-DedicatedRecoveryBrowser
        Write-JsonLine ([ordered]@{
            status = "automatic_solver_recovery_in_progress"
            snapshot = $snapshot
            closed_recovery_browser_count = $closedBrowserCount
            note = "PC2 reports an automatic solver recovery state. PC1 remains silent until an explicit manual-only state persists."
        })
        exit 0
    }

    $observation = Read-ManualAuthObservation -Path $StatePath
    $manualRequiredSince = $null
    if ($observation.ManualRequiredSince) {
        try {
            $manualRequiredSince = [datetime]::Parse([string]$observation.ManualRequiredSince)
        }
        catch {
            $manualRequiredSince = $null
        }
    }
    if ($null -eq $manualRequiredSince) {
        $manualRequiredSince = Get-Date
        Write-ManualAuthObservation -Path $StatePath -ManualRequiredSince $manualRequiredSince -Snapshot $snapshot
    }
    $manualGraceEndsAt = $manualRequiredSince.AddMinutes($ManualAuthGraceMinutes)
    if ((Get-Date) -lt $manualGraceEndsAt) {
        $closedBrowserCount = Stop-DedicatedRecoveryBrowser
        Write-JsonLine ([ordered]@{
            status = "manual_auth_grace_period"
            manual_required_since = $manualRequiredSince.ToString("o")
            grace_minutes = $ManualAuthGraceMinutes
            grace_ends_at = $manualGraceEndsAt.ToString("o")
            snapshot = $snapshot
            closed_recovery_browser_count = $closedBrowserCount
            note = "PC2 automatic solving remains primary during the grace period. PC1 opens only after the manual-only state persists for the full exceptional-recovery window."
        })
        exit 0
    }

    Send-OperationalAlert -EventName "manual_auth_required" -Payload @{
        snapshot = $snapshot
        task_name = $TaskName
        task_path = $TaskPath
        note = "PC1 official watchdog requested for manual Taobao verification."
    }
    $state = Read-RecoveryState -Path $StatePath
    $lastTriggeredRaw = $state.LastTriggeredAt
    if ($lastTriggeredRaw) {
        try {
            $lastTriggeredAt = [datetime]::Parse($lastTriggeredRaw)
            $cooldownEndsAt = $lastTriggeredAt.AddMinutes($RecoveryCooldownMinutes)
            if ((Get-Date) -lt $cooldownEndsAt) {
                Write-JsonLine ([ordered]@{
                    status = "manual_auth_recovery_cooldown_active"
                    recovery_cooldown_minutes = $RecoveryCooldownMinutes
                    last_triggered_at = $lastTriggeredAt.ToString("o")
                    cooldown_ends_at = $cooldownEndsAt.ToString("o")
                    snapshot = $snapshot
                    note = "Manual auth already requested recently. This script will not start the watchdog during cooldown."
                })
                exit 0
            }
        }
        catch {
        }
    }

    $task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Send-OperationalAlert -EventName "watchdog_task_missing" -Payload @{
            snapshot = $snapshot
            task_name = $TaskName
            task_path = $TaskPath
        }
        Write-JsonLine ([ordered]@{
            status = "watchdog_task_missing"
            watchdog_task_name = $TaskName
            watchdog_task_path = $TaskPath
            snapshot = $snapshot
            note = "Register scripts\\register-taobao-login-watchdog-task.ps1 first. This script does not solve captcha, drag sliders, or print cookie value fields."
        })
        exit 2
    }

    if ([string]$task.State -eq "Running") {
        Write-JsonLine ([ordered]@{
            status = "manual_auth_watchdog_already_running"
            watchdog_task_name = $TaskName
            watchdog_task_path = $TaskPath
            snapshot = $snapshot
            note = "Complete verification in the visible browser window. This script queues the watchdog recovery path and does not print cookie value fields."
        })
        exit 0
    }

    if ($DryRun) {
        Write-JsonLine ([ordered]@{
            status = "would_trigger_manual_auth_watchdog"
            watchdog_task_name = $TaskName
            watchdog_task_path = $TaskPath
            snapshot = $snapshot
            note = "DryRun did not start the official watchdog for manual Taobao verification and never prints cookie value fields."
        })
        exit 0
    }

    Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
    $now = Get-Date
    Write-RecoveryState -Path $StatePath -LastTriggeredAt $now -Snapshot $snapshot
    Send-OperationalAlert -EventName "triggered_manual_auth_watchdog" -Payload @{
        snapshot = $snapshot
        task_name = $TaskName
        task_path = $TaskPath
        last_triggered_at = $now.ToString("o")
    }
    Write-JsonLine ([ordered]@{
        status = "triggered_manual_auth_watchdog"
        watchdog_task_name = $TaskName
        watchdog_task_path = $TaskPath
        last_triggered_at = $now.ToString("o")
        snapshot = $snapshot
        note = "The login watchdog was started for manual Taobao verification. This script queues the configured captcha solver and does not print cookie value fields."
    })
    exit 0
}


if (-not $shouldTrigger) {
    Clear-ManualAuthObservation -Path $StatePath
    $closedBrowserCount = Stop-DedicatedRecoveryBrowser
    Write-JsonLine ([ordered]@{
        status = "healthy_or_no_recovery_needed"
        snapshot = $snapshot
        closed_recovery_browser_count = $closedBrowserCount
        note = "This script opens only the official Taobao watchdog when needed and never prints cookie value fields."
    })
    exit 0
}

$state = Read-RecoveryState -Path $StatePath
$lastTriggeredRaw = $state.LastTriggeredAt
if ($lastTriggeredRaw) {
    try {
        $lastTriggeredAt = [datetime]::Parse($lastTriggeredRaw)
        $cooldownEndsAt = $lastTriggeredAt.AddMinutes($RecoveryCooldownMinutes)
        if ((Get-Date) -lt $cooldownEndsAt) {
            Write-JsonLine ([ordered]@{
                status = "recovery_cooldown_active"
                recovery_cooldown_minutes = $RecoveryCooldownMinutes
                last_triggered_at = $lastTriggeredAt.ToString("o")
                cooldown_ends_at = $cooldownEndsAt.ToString("o")
                snapshot = $snapshot
                note = "This script opens only the official Taobao watchdog when needed and never prints cookie value fields."
            })
            exit 0
        }
    }
    catch {
        # Ignore malformed state and allow a fresh trigger.
    }
}

$task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Send-OperationalAlert -EventName "watchdog_task_missing" -Payload @{
        snapshot = $snapshot
        task_name = $TaskName
        task_path = $TaskPath
    }
    Write-JsonLine ([ordered]@{
        status = "watchdog_task_missing"
        watchdog_task_name = $TaskName
        watchdog_task_path = $TaskPath
        snapshot = $snapshot
        note = "Register scripts\\register-taobao-login-watchdog-task.ps1 first. This script does not solve captcha, drag sliders, or print cookie value fields."
    })
    exit 2
}

if ([string]$task.State -eq "Running") {
    Write-JsonLine ([ordered]@{
        status = "watchdog_already_running"
        watchdog_task_name = $TaskName
        watchdog_task_path = $TaskPath
        snapshot = $snapshot
        note = "Complete verification in the visible browser window if the configured captcha solver cannot finish it. This script queues the watchdog recovery path and does not print cookie value fields."
    })
    exit 0
}

if ($DryRun) {
    Write-JsonLine ([ordered]@{
        status = "would_trigger_official_watchdog"
        watchdog_task_name = $TaskName
        watchdog_task_path = $TaskPath
        snapshot = $snapshot
        note = "DryRun did not start the official watchdog and never prints cookie value fields."
    })
    exit 0
}

Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
$now = Get-Date
Write-RecoveryState -Path $StatePath -LastTriggeredAt $now -Snapshot $snapshot
Send-OperationalAlert -EventName "triggered_official_watchdog" -Payload @{
    snapshot = $snapshot
    task_name = $TaskName
    task_path = $TaskPath
    last_triggered_at = $now.ToString("o")
}

Write-JsonLine ([ordered]@{
    status = "triggered_official_watchdog"
    watchdog_task_name = $TaskName
    watchdog_task_path = $TaskPath
    last_triggered_at = $now.ToString("o")
    snapshot = $snapshot
    note = "The login watchdog was started for verification recovery. It queues the configured captcha solver and does not print cookie value fields."
})
