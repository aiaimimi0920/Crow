param(
    [string]$TaskName = "FapaiFangPostgresBackup",
    [string]$DataRoot = "",
    [int]$IntervalMinutes = 15,
    [int]$KeepLast = 96,
    [int]$CommandTimeoutSeconds = 900,
    [int]$ExecutionTimeLimitMinutes = 20,
    [string]$TaskPath = "\FapaiFang\"
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

if ($IntervalMinutes -lt 1) {
    throw "IntervalMinutes must be at least 1."
}

if ($KeepLast -lt 1) {
    throw "KeepLast must be at least 1."
}

if ($CommandTimeoutSeconds -lt 1) {
    throw "CommandTimeoutSeconds must be at least 1."
}

if ($ExecutionTimeLimitMinutes -lt 1) {
    throw "ExecutionTimeLimitMinutes must be at least 1."
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backupScript = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\backup-postgres-to-host.ps1"))
if (-not (Test-Path -LiteralPath $backupScript)) {
    throw "Backup script not found: $backupScript"
}

$taskDataRoot = Convert-DataRootForScheduledTask -Path $DataRoot
$workingDirectory = if ($env:TEMP) { $env:TEMP } else { "C:\Windows\Temp" }

$scriptArgs = @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$backupScript`"",
    "-DataRoot", "`"$taskDataRoot`"",
    "-KeepLast", $KeepLast,
    "-CommandTimeoutSeconds", $CommandTimeoutSeconds
)

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ($scriptArgs -join " ") `
    -WorkingDirectory $workingDirectory

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
    -Description "Create verified FapaiFang PostgreSQL dumps under $taskDataRoot."

Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath $TaskPath `
    -InputObject $task `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
