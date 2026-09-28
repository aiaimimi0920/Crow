param(
    [string]$TaskName = "FapaiFangDataSync",
    [string]$DataRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) "FPFData"),
    [int]$IntervalMinutes = 15,
    [string]$TaskPath = "\FapaiFang\",
    [switch]$IncludePostgres
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

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$syncScript = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\sync-docker-data-to-host.ps1"))
if (-not (Test-Path -LiteralPath $syncScript)) {
    throw "Sync script not found: $syncScript"
}

$taskDataRoot = Convert-DataRootForScheduledTask -Path $DataRoot
$workingDirectory = if ($env:TEMP) { $env:TEMP } else { "C:\Windows\Temp" }

$scriptArgs = @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$syncScript`"",
    "-DataRoot", "`"$taskDataRoot`""
)
if (-not $IncludePostgres) {
    $scriptArgs += "-SkipPostgres"
}

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
    -StartWhenAvailable

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Sync FapaiFang Docker collector data to $taskDataRoot."

Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath $TaskPath `
    -InputObject $task `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
