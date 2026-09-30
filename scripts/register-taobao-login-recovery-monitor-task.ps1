param(
    [string]$TaskName = "FapaiFangTaobaoLoginRecoveryMonitor",
    [string]$DataRoot = "",
    [int]$IntervalMinutes = 1,
    [int]$RecentMinutes = 3,
    [int]$MinRecentSeedItems = 1,
    [int]$StaleSeedMinutes = 3,
    [int]$MissingPayloadThreshold = 20,
    [int]$RecoveryCooldownMinutes = 10,
    [int]$ManualAuthGraceMinutes = 30,
    [string]$WatchdogTaskName = "FapaiFangTaobaoLoginWatchdog",
    [string]$TaskPath = "\FapaiFang\",
    [int]$ExecutionTimeLimitMinutes = 2
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")
$DataRoot = Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot

function Convert-DataRootForScheduledTask {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ($Path -match "^[A-Za-z]:\\") {
        $driveName = $Path.Substring(0, 1)
        $drive = Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue
        if ($drive -and $drive.DisplayRoot) {
            $relativePath = $Path.Substring(3)
            return (Join-Path $drive.DisplayRoot $relativePath)
        }
    }

    return [System.IO.Path]::GetFullPath($Path)
}

function Convert-ToPowerShellSingleQuotedArgument {
    param([Parameter(Mandatory = $true)][string]$Value)

    return "'" + ($Value -replace "'", "''") + "'"
}

if ($IntervalMinutes -lt 1) {
    throw "IntervalMinutes must be at least 1."
}
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
if ($ExecutionTimeLimitMinutes -lt 1) {
    throw "ExecutionTimeLimitMinutes must be at least 1."
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$triggerScript = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\trigger-taobao-login-recovery-if-needed.ps1"))
if (-not (Test-Path -LiteralPath $triggerScript)) {
    throw "Taobao login recovery trigger script not found: $triggerScript"
}

$taskDataRoot = Convert-DataRootForScheduledTask -Path $DataRoot
$runtimeDir = Join-Path $taskDataRoot "runtime"
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

$wrapperScript = Join-Path $runtimeDir "run-taobao-login-recovery-monitor.ps1"
$monitorLogPath = Join-Path $runtimeDir "taobao-login-recovery-monitor.log"
$taskWorkingDirectory = $runtimeDir

$monitorLogLiteral = Convert-ToPowerShellSingleQuotedArgument $monitorLogPath
$triggerScriptLiteral = Convert-ToPowerShellSingleQuotedArgument $triggerScript
$taskDataRootLiteral = Convert-ToPowerShellSingleQuotedArgument $taskDataRoot
$watchdogTaskNameLiteral = Convert-ToPowerShellSingleQuotedArgument $WatchdogTaskName
$taskPathLiteral = Convert-ToPowerShellSingleQuotedArgument $TaskPath
$startLogLine = '"[$timestamp] FapaiFangTaobaoLoginRecoveryMonitor starting." | Add-Content -LiteralPath ' + $monitorLogLiteral + ' -Encoding UTF8'
$invokeTriggerLine = '& ' + $triggerScriptLiteral +
    ' -DataRoot ' + $taskDataRootLiteral +
    ' -RecentMinutes ' + $RecentMinutes +
    ' -MinRecentSeedItems ' + $MinRecentSeedItems +
    ' -StaleSeedMinutes ' + $StaleSeedMinutes +
    ' -MissingPayloadThreshold ' + $MissingPayloadThreshold +
    ' -RecoveryCooldownMinutes ' + $RecoveryCooldownMinutes +
    ' -ManualAuthGraceMinutes ' + $ManualAuthGraceMinutes +
    ' -TaskName ' + $watchdogTaskNameLiteral +
    ' -TaskPath ' + $taskPathLiteral +
    ' *>> ' + $monitorLogLiteral
$exitLogLine = '"[$timestamp] FapaiFangTaobaoLoginRecoveryMonitor exit=$exitCode." | Add-Content -LiteralPath ' + $monitorLogLiteral + ' -Encoding UTF8'

$wrapperLines = @(
    '$ErrorActionPreference = "Continue"',
    '$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"',
    $startLogLine,
    $invokeTriggerLine,
    '$exitCode = $LASTEXITCODE',
    '$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"',
    $exitLogLine,
    'exit $exitCode'
)
Set-Content -LiteralPath $wrapperScript -Value $wrapperLines -Encoding UTF8

$scriptArgs = @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$wrapperScript`""
)

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ($scriptArgs -join " ") `
    -WorkingDirectory $taskWorkingDirectory

$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes $ExecutionTimeLimitMinutes)

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "FapaiFangTaobaoLoginRecoveryMonitor checks DB seed throughput and retryable list-page failures, then starts the official Taobao watchdog for manual verification when collection is stalled."

Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath $TaskPath `
    -InputObject $task `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
