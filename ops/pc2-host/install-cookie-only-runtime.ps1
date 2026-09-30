param(
  [string]$StagingDir = 'C:\fapaifang-worker\staging\cookie-only-runtime',
  [string]$InstallDir = 'C:\fapaifang-worker\ops',
  [string]$WorkerRoot = 'C:\fapaifang-worker',
  [string]$BackupRoot = 'C:\fapaifang-worker\backup\pc2-cookie-only-runtime',
  [string]$TaskName = 'FapaiPc2RealWorkerLauncher',
  [string]$TaskPath = '\'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$files = @(
  'crow-environment.ps1',
  'runtime\project-environment.ps1',
  'runtime\compose-environment-file.ps1',
  'apply-cookie-only-worker-env.ps1',
  'import-host-direct-analysis-env.ps1',
  'launch-host-direct-workers.ps1',
  'load-host-direct-nas-env.ps1',
  'register-host-direct-worker-watchdog.ps1',
  'start-host-direct-analysis-worker.ps1',
  'start-host-direct-analysis-worker-2.ps1',
  'start-host-direct-analysis-worker-3.ps1',
  'start-host-direct-detail-worker.ps1',
  'start-host-direct-detail-worker-2.ps1',
  'start-host-direct-detail-worker-3.ps1',
  'start-host-direct-seed-worker.ps1'
)

function Test-PowerShellFile {
  param([Parameter(Mandatory = $true)][string]$Path)

  $parseErrors = $null
  $tokens = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile(
    $Path,
    [ref]$tokens,
    [ref]$parseErrors
  )
  if ($parseErrors -and $parseErrors.Count -gt 0) {
    $messages = @($parseErrors | ForEach-Object { $_.Message }) -join '; '
    throw ("PowerShell parse failed for {0}: {1}" -f $Path, $messages)
  }
}

function Copy-IfExists {
  param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$DestinationPath
  )

  if (-not (Test-Path -LiteralPath $SourcePath)) {
    return $false
  }

  $destinationParent = Split-Path -Parent $DestinationPath
  if ($destinationParent) {
    New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
  }
  Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
  return $true
}

$envFile = Join-Path $WorkerRoot 'env.worker.local'
$applyScript = Join-Path $InstallDir 'apply-cookie-only-worker-env.ps1'
$registerScript = Join-Path $InstallDir 'register-host-direct-worker-watchdog.ps1'

if (-not (Test-Path -LiteralPath $StagingDir)) {
  throw "PC2 staging directory does not exist: $StagingDir"
}

foreach ($name in $files) {
  $sourcePath = Join-Path $StagingDir $name
  if (-not (Test-Path -LiteralPath $sourcePath)) {
    throw "PC2 staging file does not exist: $sourcePath"
  }
  Test-PowerShellFile -Path $sourcePath
}

$existingTask = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($null -ne $existingTask) {
  Stop-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = Join-Path $BackupRoot $timestamp
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

foreach ($name in $files) {
  $installedPath = Join-Path $InstallDir $name
  $backupPath = Join-Path $backupDir $name
  [void](Copy-IfExists -SourcePath $installedPath -DestinationPath $backupPath)
}
[void](Copy-IfExists -SourcePath $envFile -DestinationPath (Join-Path $backupDir 'env.worker.local'))

try {
  foreach ($name in $files) {
    $sourcePath = Join-Path $StagingDir $name
    $destinationPath = Join-Path $InstallDir $name
    $destinationParent = Split-Path -Parent $destinationPath
    if ($destinationParent) {
      New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
    }
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
    Test-PowerShellFile -Path $destinationPath
  }

  $cutoverOutput = & $applyScript
  $cutoverJson = @($cutoverOutput | Where-Object { $_ -is [string] -and $_.Trim() }) | Select-Object -Last 1
  if (-not $cutoverJson) {
    throw 'PC2 cookie-only environment apply script returned no JSON summary.'
  }
  $cutover = $cutoverJson | ConvertFrom-Json

  & $registerScript -TaskName $TaskName -TaskPath $TaskPath | Out-Null
  Start-Sleep -Seconds 2
  $taskState = (Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath).State

  [pscustomobject]@{
    backup_dir = $backupDir
    staging_dir = $StagingDir
    install_dir = $InstallDir
    deployed_files = $files
    env_mode = $cutover.mode
    detail_worker_count = $cutover.detail_worker_count
    analysis_worker_count = $cutover.analysis_worker_count
    snapshot_exists = $cutover.snapshot_exists
    task_name = $TaskName
    task_state = [string]$taskState
  } | ConvertTo-Json -Compress
} catch {
  foreach ($name in $files) {
    $backupPath = Join-Path $backupDir $name
    $destinationPath = Join-Path $InstallDir $name
    if (Test-Path -LiteralPath $backupPath) {
      Copy-Item -LiteralPath $backupPath -Destination $destinationPath -Force
    }
  }
  $backupEnv = Join-Path $backupDir 'env.worker.local'
  if (Test-Path -LiteralPath $backupEnv) {
    Copy-Item -LiteralPath $backupEnv -Destination $envFile -Force
  }
  if (Test-Path -LiteralPath $registerScript) {
    try {
      & $registerScript -TaskName $TaskName -TaskPath $TaskPath | Out-Null
    } catch {
      Write-Warning "PC2 worker watchdog restart after rollback failed: $($_.Exception.Message)"
    }
  }
  throw
}
