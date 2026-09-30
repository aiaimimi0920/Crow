param(
    [string]$TaskName = "FapaiFangNasAuthRecovery",
    [string]$TaskPath = "\FapaiFang\",
    [string]$ApiBase = "",
    [string]$DataRoot = "",
    [string]$OutputPath = "",
    [string]$TokenPath = "",
    [string]$ApiCaFile = "",
    [string]$Python = "",
    [string]$ProfileDir = "",
    [string]$BrowserPath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    [int]$Port = 9225,
    [int]$IntervalMinutes = 1,
    [int]$LoginWindowSeconds = 300,
    [int]$ExecutionTimeLimitMinutes = 10,
    [ValidateSet("NoConsole", "Console")][string]$LauncherMode = "NoConsole",
    [switch]$UseSystemProxy,
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")
if (-not $ProfileDir) { $ProfileDir = Join-Path (Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot) "chrome-cdp-profile-pc1-human-clean" }
$DataRoot = Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot
. (Join-Path $PSScriptRoot "collection-api-origin.ps1")
if (-not $ApiBase) {
    $ApiBase = if ($env:FAPAI_COLLECTOR_API_BASE) { $env:FAPAI_COLLECTOR_API_BASE } else { $env:FAPAI_API_BASE_URL }
}
$ApiBase = (ConvertTo-CollectionApiOrigin $ApiBase) + "/api"
if (-not $ApiCaFile) { $ApiCaFile = $env:FAPAI_API_CA_FILE }
if ($ApiCaFile -and -not (Test-Path -LiteralPath $ApiCaFile -PathType Leaf)) {
    throw "Collection API CA file is unavailable."
}
if ($IntervalMinutes -lt 1) { throw "IntervalMinutes must be at least 1." }
if ($LoginWindowSeconds -lt 300) { throw "LoginWindowSeconds must be at least 300." }
if ($ExecutionTimeLimitMinutes -lt 5) { throw "ExecutionTimeLimitMinutes must be at least 5." }

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pythonResolver = Join-Path $repoRoot "scripts\resolve-pc1-auth-python.ps1"
if (-not (Test-Path -LiteralPath $pythonResolver -PathType Leaf)) {
    throw "PC1 auth Python resolver not found: $pythonResolver"
}
. $pythonResolver
$resolvedPython = Resolve-Pc1AuthPython -Requested $Python
$watcher = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\watch-pc1-nas-auth-recovery.ps1"))
if (-not (Test-Path -LiteralPath $watcher)) {
    throw "NAS auth recovery watcher not found: $watcher"
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $DataRoot "secrets\nodes\pc2\taobao-cookies.json"
}
if (-not $TokenPath) {
    $TokenPath = if ($env:FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE) {
        $env:FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE
    } else {
        Join-Path $DataRoot "secrets\nas-auth-recovery.token"
    }
}

$arguments = @(
    "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
    "-File", "`"$watcher`"",
    "-ApiBase", "`"$ApiBase`"",
    "-DataRoot", "`"$DataRoot`"",
    "-OutputPath", "`"$OutputPath`"",
    "-TokenPath", "`"$TokenPath`"",
    "-Python", "`"$resolvedPython`"",
    "-ProfileDir", "`"$ProfileDir`"",
    "-BrowserPath", "`"$BrowserPath`"",
    "-Port", $Port,
    "-LoginWindowSeconds", $LoginWindowSeconds
)
if ($UseSystemProxy) {
    $arguments += "-UseSystemProxy"
}
if ($ApiCaFile) {
    $arguments += @("-ApiCaFile", "`"$ApiCaFile`"")
}

$executable = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if ($LauncherMode -eq "NoConsole") {
    $pythonw = Join-Path (Split-Path -Parent $resolvedPython) "pythonw.exe"
    $launcher = Join-Path $repoRoot "tools\background_task_launcher.py"
    foreach ($required in @($pythonw, $launcher)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "No-console task launcher dependency is unavailable: $required"
        }
    }
    $statusPath = Join-Path $DataRoot "runtime\pc1-nas-auth-task.json"
    $arguments = @(
        "-I", "`"$launcher`"", "--status-path", "`"$statusPath`"",
        "--", "`"$executable`""
    ) + $arguments
    $executable = $pythonw
}

$action = New-ScheduledTaskAction `
    -Execute $executable `
    -Argument ($arguments -join " ") `
    -WorkingDirectory $repoRoot
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
    -Description "Polls the NAS single-flight auth recovery job, keeps one five-minute PC1 login window, and publishes only validated cookie metadata."
Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -InputObject $task -Force | Out-Null
Enable-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath | Out-Null
if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
}
Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
