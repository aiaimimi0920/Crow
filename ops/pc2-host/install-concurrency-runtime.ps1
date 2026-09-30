param(
  [string]$StagingDir = 'C:\fapaifang-worker\staging\concurrency-runtime',
  [string]$InstallDir = 'C:\fapaifang-worker\ops',
  [string]$WorkerRoot = 'C:\fapaifang-worker',
  [string]$BackupRoot = 'C:\fapaifang-worker\backup\pc2-concurrency-runtime',
  [string]$TaskName = 'FapaiPc2RealWorkerLauncher',
  [string]$TaskPath = '\',
  [ValidateRange(3, 8)][int]$DetailWorkerCount = 4,
  [ValidateRange(3, 8)][int]$AnalysisWorkerCount = 4
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$files = @(
  'crow-environment.ps1',
  'runtime\project-environment.ps1',
  'runtime\compose-environment-file.ps1',
  'apply-worker-concurrency-env.ps1',
  'launch-host-direct-workers.ps1',
  'start-host-direct-analysis-worker.ps1',
  'start-host-direct-detail-worker.ps1',
  'load-host-worker-env.ps1',
  'load-host-direct-nas-env.ps1',
  'start-host-detail-worker.ps1',
  'start-host-seed-worker.ps1',
  'start-host-seed-worker-2.ps1',
  'start-host-direct-seed-worker.ps1',
  'start-host-direct-detail-worker-2.ps1',
  'start-host-direct-detail-worker-3.ps1',
  'start-host-direct-analysis-worker-2.ps1',
  'start-host-direct-analysis-worker-3.ps1',
  'start-pc2-local-solver.ps1',
  'launch-host-direct-workers\analysis-backend.ps1',
  'launch-host-direct-workers\control-plane.ps1',
  'launch-host-direct-workers\process-lifecycle.ps1',
  'launch-host-direct-workers\worker-specs.ps1',
  'launch-host-direct-workers\worker-supervision.ps1'
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
$applyScript = Join-Path $InstallDir 'apply-worker-concurrency-env.ps1'
$registerScript = Join-Path $InstallDir 'register-host-direct-worker-watchdog.ps1'

if (-not (Test-Path -LiteralPath $StagingDir)) {
  throw "PC2 staging directory does not exist: $StagingDir"
}
if (-not (Test-Path -LiteralPath $registerScript)) {
  throw "PC2 watchdog registration script does not exist: $registerScript"
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
  [void](Copy-IfExists -SourcePath (Join-Path $InstallDir $name) -DestinationPath (Join-Path $backupDir $name))
}
[void](Copy-IfExists -SourcePath $envFile -DestinationPath (Join-Path $backupDir 'env.worker.local'))

try {
  foreach ($name in $files) {
    $destinationPath = Join-Path $InstallDir $name
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destinationPath) | Out-Null
    Copy-Item -LiteralPath (Join-Path $StagingDir $name) -Destination $destinationPath -Force
    Test-PowerShellFile -Path $destinationPath
  }

  $applyOutput = & $applyScript -EnvFile $envFile -DetailWorkerCount $DetailWorkerCount -AnalysisWorkerCount $AnalysisWorkerCount
  $applyJson = @($applyOutput | Where-Object { $_ -is [string] -and $_.Trim() }) | Select-Object -Last 1
  if (-not $applyJson) {
    throw 'PC2 concurrency environment apply script returned no JSON summary.'
  }
  $applied = $applyJson | ConvertFrom-Json

  & $registerScript -TaskName $TaskName -TaskPath $TaskPath | Out-Null
  Start-Sleep -Seconds 2
  $taskState = (Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath).State

  [pscustomobject]@{
    backup_dir = $backupDir
    staging_dir = $StagingDir
    install_dir = $InstallDir
    deployed_files = $files
    detail_worker_count = $applied.detail_worker_count
    analysis_worker_count = $applied.analysis_worker_count
    unrelated_settings_preserved = $applied.unrelated_settings_preserved
    task_name = $TaskName
    task_state = [string]$taskState
  } | ConvertTo-Json -Compress
} catch {
  foreach ($name in $files) {
    $backupPath = Join-Path $backupDir $name
    if (Test-Path -LiteralPath $backupPath) {
      Copy-Item -LiteralPath $backupPath -Destination (Join-Path $InstallDir $name) -Force
    }
  }
  $backupEnv = Join-Path $backupDir 'env.worker.local'
  if (Test-Path -LiteralPath $backupEnv) {
    Copy-Item -LiteralPath $backupEnv -Destination $envFile -Force
  }
  try {
    & $registerScript -TaskName $TaskName -TaskPath $TaskPath | Out-Null
  } catch {
    Write-Warning "PC2 worker watchdog restart after rollback failed: $($_.Exception.Message)"
  }
  throw
}
