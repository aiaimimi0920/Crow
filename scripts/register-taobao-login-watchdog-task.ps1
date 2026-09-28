param(
    [string]$TaskName = "FapaiFangTaobaoLoginWatchdog",
    [string]$DataRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) "FPFData"),
    [string]$OutputPath = "",
    [string]$AlertWebhookUrl = "",
    [int]$WaitSeconds = 600,
    [int]$PollSeconds = 5,
    [int]$Port = 9223,
    [string]$TaskPath = "\FapaiFang\",
    [int]$ExecutionTimeLimitMinutes = 15,
    [switch]$UseSystemProxy
)

$ErrorActionPreference = "Stop"

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

if ($WaitSeconds -lt 0) {
    throw "WaitSeconds must not be negative."
}
if ($ExecutionTimeLimitMinutes -lt 1) {
    throw "ExecutionTimeLimitMinutes must be at least 1."
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$watchdogScript = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\taobao-login-watchdog.ps1"))
if (-not (Test-Path -LiteralPath $watchdogScript)) {
    throw "Watchdog script not found: $watchdogScript"
}

$taskDataRoot = Convert-DataRootForScheduledTask -Path $DataRoot
$taskOutputPath = if ($OutputPath) {
    Convert-DataRootForScheduledTask -Path $OutputPath
} else {
    ""
}
$taskAlertWebhookUrl = [string]$AlertWebhookUrl
$workingDirectory = $repoRoot

$scriptArgs = @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$watchdogScript`"",
    "-DataRoot", "`"$taskDataRoot`"",
    "-Port", $Port,
    "-WaitSeconds", $WaitSeconds,
    "-PollSeconds", $PollSeconds
)
if ($taskOutputPath) {
    $scriptArgs += @("-OutputPath", "`"$taskOutputPath`"")
}
if ($taskAlertWebhookUrl) {
    $scriptArgs += @("-AlertWebhookUrl", "`"$taskAlertWebhookUrl`"")
}
if ($UseSystemProxy) {
    $scriptArgs += "-UseSystemProxy"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ($scriptArgs -join " ") `
    -WorkingDirectory $workingDirectory

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
    -Principal $principal `
    -Settings $settings `
    -Description "On-demand FapaiFang Taobao recovery task. The recovery monitor starts it only when PC1 human authentication is required."

Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath $TaskPath `
    -InputObject $task `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
