param(
  [int]$PollSeconds = 30,
  [int]$SeedSummaryMaxAgeSeconds = 240,
  [int]$DetailSummaryMaxAgeSeconds = 300,
  [int]$AnalysisSummaryMaxAgeSeconds = 600,
  [int]$StartupGraceSeconds = 120,
  [int]$CdpFailureThreshold = 3,
  [int]$CdpRestartCooldownSeconds = 300,
  [int]$AnalysisBackendRetryCooldownSeconds = 900,
  [int]$DetailWorkerCount = 0,
  [int]$AnalysisWorkerCount = 0,
  [switch]$Once
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'crow-environment.ps1')

$root = 'C:\fapaifang-worker'
$workerMutex = New-Object System.Threading.Mutex($false, 'Global\FapaiFangPc2RealWorkers')
if (-not $workerMutex.WaitOne(0)) {
  # Logon triggers and an operator-started task can overlap briefly.  Only one
  # watchdog may supervise the worker set; a second instance must exit before
  # it can spawn duplicate seed/detail/analysis processes.
  exit 0
}
$envFile = Join-Path $root 'env.worker.local'
Import-CrowOperatorEnvironment -Path $envFile
$logDir = Join-Path $root 'logs\codex-pc2-real'
$sharedRoot = if ((Get-CrowEnvironmentValue -Name 'CROW_NAS_SHARE_ROOT' -PathValue)) {
  (Get-CrowEnvironmentValue -Name 'CROW_NAS_SHARE_ROOT' -PathValue)
} else {
  '\\192.168.15.200\home\project\project\FPFData'
}
$watchdogLog = Join-Path $logDir 'worker-watchdog.log'
$cdpRecoveryLog = Join-Path $logDir 'cdp-recovery.log'
$cdpEndpoint = if ((Get-CrowEnvironmentValue -Name 'CROW_CDP_ENDPOINT')) {
  (Get-CrowEnvironmentValue -Name 'CROW_CDP_ENDPOINT')
} else {
  'http://127.0.0.1:9223'
}
$externalCdp = (Get-CrowEnvironmentValue -Name 'CROW_CDP_EXTERNAL') -eq '1'
$cookieSnapshotPreferred = (Get-CrowEnvironmentValue -Name 'CROW_COOKIE_SNAPSHOT_PREFER') -eq '1'
$collectorRequiresCdp = -not ($externalCdp -and $cookieSnapshotPreferred)
$apiBaseUrl = if ((Get-CrowEnvironmentValue -Name 'CROW_API_BASE_URL')) {
  (Get-CrowEnvironmentValue -Name 'CROW_API_BASE_URL').TrimEnd('/')
} else {
  'http://192.168.15.200:8001/api'
}
$cdpProfileDir = 'C:\Users\Public\nas_home\AI\FPFData\edge-cdp-profile-pc2'
$cdpBrowserScript = Join-Path $root 'src\scripts\start-taobao-cdp-browser.ps1'
$consecutiveCdpFailures = 0
$lastCdpRestartAt = [datetime]::MinValue
$analysisBackendRetryAt = @{}
$analysisUnavailableSummaryWriteTicks = @{}
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$workerWatchdogModuleRoot = Join-Path $PSScriptRoot 'launch-host-direct-workers'
. (Join-Path $workerWatchdogModuleRoot 'worker-specs.ps1')
. (Join-Path $workerWatchdogModuleRoot 'control-plane.ps1')
. (Join-Path $workerWatchdogModuleRoot 'process-lifecycle.ps1')
. (Join-Path $workerWatchdogModuleRoot 'analysis-backend.ps1')
. (Join-Path $workerWatchdogModuleRoot 'worker-supervision.ps1')

Write-WatchdogLog 'pc2 worker watchdog booted'
Initialize-AnalysisUnavailableSummaryBaseline
while ($true) {
  $pauseState = Get-CollectionPauseState
  $collectionPaused = [bool]$pauseState.global_paused
  $seedCollectionPaused = [bool]$pauseState.seed_paused
  $detailCollectionPaused = [bool]$pauseState.detail_paused
  if ($seedCollectionPaused -or $detailCollectionPaused) {
    Stop-WorkersForCollectionPause `
      -SeedPaused:$seedCollectionPaused `
      -DetailPaused:$detailCollectionPaused
  }
  $cdpRequired = @($workerSpecs | Where-Object { $_.RequiresCdp }).Count -gt 0
  $cdpReady = -not $cdpRequired
  if ($cdpRequired) {
    try {
      $cdpReady = Ensure-CdpBrowser
    } catch {
      Write-WatchdogLog "watchdog cdp check failed: $($_.Exception.Message)"
    }
  }
  foreach ($spec in $workerSpecs) {
    $scopePaused = if ([string]$spec.Name -eq 'seed') {
      $seedCollectionPaused
    } elseif ([string]$spec.Name -like 'detail-*') {
      $detailCollectionPaused
    } else {
      $false
    }
    if (($scopePaused -and $spec.StopsWhenCollectionPaused) -or ($spec.RequiresCdp -and -not $cdpReady)) {
      continue
    }
    try {
      Ensure-Worker -Spec $spec
    } catch {
      Write-WatchdogLog "watchdog error for $($spec.Name): $($_.Exception.Message)"
    }
  }
  if ($cdpRequired -and -not $cdpReady) {
    Write-WatchdogLog 'cdp unavailable; skipping CDP-dependent worker supervision'
  }
  if ($Once) {
    break
  }
  Start-Sleep -Seconds $PollSeconds
}
