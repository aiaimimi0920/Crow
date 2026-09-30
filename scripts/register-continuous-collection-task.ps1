param(
    [string]$TaskName = "FapaiFangContinuousCollection",
    [string]$DataRoot = "",
    [int]$IntervalMinutes = 15,
    [int]$Port = 9223,
    [string]$Python = "python",
    [string]$TaskPath = "\FapaiFang\",
    [int]$ExecutionTimeLimitMinutes = 30,
    [switch]$Build
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
if ($ExecutionTimeLimitMinutes -lt 1) {
    throw "ExecutionTimeLimitMinutes must be at least 1."
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$startScript = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\start-continuous-collection.ps1"))
if (-not (Test-Path -LiteralPath $startScript)) {
    throw "Continuous collection script not found: $startScript"
}

$taskDataRoot = Convert-DataRootForScheduledTask -Path $DataRoot

$scriptArgs = @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$startScript`"",
    "-DataRoot", "`"$taskDataRoot`"",
    "-Port", $Port,
    "-Python", "`"$Python`""
)
if ($Build) {
    $scriptArgs += "-Build"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ($scriptArgs -join " ") `
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
    -Description "FapaiFangContinuousCollection periodically runs the health-gated collection startup. It opens official Taobao verification when required and starts workers only after the normal watchdog succeeds."

Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath $TaskPath `
    -InputObject $task `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
