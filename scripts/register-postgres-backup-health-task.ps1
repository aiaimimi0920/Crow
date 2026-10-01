param(
    [string]$TaskName = "FapaiFangPostgresBackupHealth",
    [string]$DataRoot = "",
    [int]$IntervalMinutes = 15,
    [int]$MaxAgeMinutes = 45,
    [long]$MinBytes = 1048576,
    [int]$CommandTimeoutSeconds = 300,
    [int]$ExecutionTimeLimitMinutes = 10,
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

if ($MaxAgeMinutes -lt 1) {
    throw "MaxAgeMinutes must be at least 1."
}

if ($MinBytes -lt 1) {
    throw "MinBytes must be at least 1."
}

if ($CommandTimeoutSeconds -lt 1) {
    throw "CommandTimeoutSeconds must be at least 1."
}

if ($ExecutionTimeLimitMinutes -lt 1) {
    throw "ExecutionTimeLimitMinutes must be at least 1."
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$healthScript = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\check-postgres-backup-health.ps1"))
if (-not (Test-Path -LiteralPath $healthScript)) {
    throw "Health check script not found: $healthScript"
}

$taskDataRoot = Convert-DataRootForScheduledTask -Path $DataRoot
$workingDirectory = if ($env:TEMP) { $env:TEMP } else { "C:\Windows\Temp" }

$scriptArgs = @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$healthScript`"",
    "-DataRoot", "`"$taskDataRoot`"",
    "-MaxAgeMinutes", $MaxAgeMinutes,
    "-MinBytes", $MinBytes,
    "-CommandTimeoutSeconds", $CommandTimeoutSeconds,
    "-SkipRestoreList"
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
    -Description "Check FapaiFang PostgreSQL backup freshness, size, and backup task result."

Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath $TaskPath `
    -InputObject $task `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
