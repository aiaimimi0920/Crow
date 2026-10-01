param(
  [string]$RequestedWorkerId = '',
  [string]$RequestedOutputDir = '',
  [string]$BrowserFallbackOverride = ''
)
. (Join-Path $PSScriptRoot 'crow-environment.ps1')


$ctx = & 'C:\fapaifang-worker\ops\load-host-direct-nas-env.ps1'
$effectiveBrowserFallbackOverride = if ($BrowserFallbackOverride -ne '') {
  $BrowserFallbackOverride
} else {
  (Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_BROWSER_FALLBACK_OVERRIDE')
}
if ($null -ne $effectiveBrowserFallbackOverride -and $effectiveBrowserFallbackOverride -ne '') {
  (Set-CrowEnvironmentValue -Name 'CROW_DETAIL_BROWSER_FALLBACK' -Value ($effectiveBrowserFallbackOverride))
}
Set-Location $ctx.SrcRoot
$workerId = if ($RequestedWorkerId) {
  $RequestedWorkerId
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_WORKER_ID')) {
  (Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_WORKER_ID')
} else {
  'pc2-real-detail-1'
}
$outputDir = if ($RequestedOutputDir) {
  $RequestedOutputDir
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_OUTPUT_DIR' -PathValue)) {
  (Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_OUTPUT_DIR' -PathValue)
} else {
  Join-Path $ctx.SharedRoot 'output\nodes\pc2-real\detail_worker'
}
$detailCdpEndpoint = if ((Get-CrowEnvironmentValue -Name 'CROW_DETAIL_CDP_ENDPOINT')) { (Get-CrowEnvironmentValue -Name 'CROW_DETAIL_CDP_ENDPOINT') } else { (Get-CrowEnvironmentValue -Name 'CROW_CDP_ENDPOINT') }
$targetSuccess = if ((Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_TARGET_SUCCESS')) { (Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_TARGET_SUCCESS') } else { '10' }
$maxAttempts = if ((Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_MAX_ATTEMPTS')) { (Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_MAX_ATTEMPTS') } else { '30' }
$activeLoopIntervalSeconds = if ((Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS')) { (Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS') } else { '0' }
$successDelaySeconds = if ((Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_SUCCESS_DELAY_SECONDS')) { (Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_SUCCESS_DELAY_SECONDS') } else { '0' }
$failureDelaySeconds = if ((Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_FAILURE_DELAY_SECONDS')) { (Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_FAILURE_DELAY_SECONDS') } else { '1' }
$solverEnabled = if ((Get-CrowEnvironmentValue -Name 'CROW_DETAIL_CAPTCHA_SOLVER_ENABLED')) {
  (Get-CrowEnvironmentValue -Name 'CROW_DETAIL_CAPTCHA_SOLVER_ENABLED')
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_CAPTCHA_SOLVER_ENABLED')) {
  (Get-CrowEnvironmentValue -Name 'CROW_CAPTCHA_SOLVER_ENABLED')
} else {
  '0'
}
$manualChallengeReportingSupported = $true
$apiStatusReachable = $false
try {
  $apiStatus = Invoke-RestMethod -Uri 'http://192.168.15.200:8001/api/status' -TimeoutSec 5
  $apiStatusReachable = $true
  $manualChallengeReportingSupported = $true
  if (
    $null -ne $apiStatus.capabilities -and
    $null -ne $apiStatus.capabilities.manual_captcha_report_v1
  ) {
    $manualChallengeReportingSupported = $apiStatus.capabilities.manual_captcha_report_v1 -eq $true
  }
} catch {
  # The manual-only endpoint is the safe default during a brief API restart.
  $manualChallengeReportingSupported = $true
}

function Find-ExistingWorkerProcess {
  $scriptPattern = [regex]::Escape('tools\detail_worker.py')
  $workerIdPattern = (
    '--worker-id\s+["'']?' +
    [regex]::Escape($workerId) +
    '["'']?(?=\s|$)'
  )
  return Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Name -eq 'python.exe' -and
      $_.CommandLine -match $scriptPattern -and
      $_.CommandLine -match $workerIdPattern
    } |
    Sort-Object CreationDate -Descending |
    Select-Object -First 1
}

$existing = Find-ExistingWorkerProcess
if ($null -ne $existing) {
  Write-Output "detail already running with pid $($existing.ProcessId)"
  exit 0
}

$args = @(
  'tools\detail_worker.py',
  '--output-dir', $outputDir,
  '--cdp-endpoint', $detailCdpEndpoint,
  '--target-success', $targetSuccess,
  '--max-attempts', $maxAttempts,
  '--item-max-attempts', '3',
  '--worker-id', $workerId,
  '--failure-cooldown-seconds', '120',
  '--loop',
  '--success-delay-seconds', $successDelaySeconds,
  '--failure-delay-seconds', $failureDelaySeconds,
  '--active-loop-interval-seconds', $activeLoopIntervalSeconds,
  '--loop-interval-seconds', '30',
  '--api-base-url', 'http://192.168.15.200:8001/api',
  '--raw-only'
)

if (
  ([string]$solverEnabled).Trim().ToLowerInvariant() -in @('1', 'true', 'yes', 'on')
) {
  $args += '--solver-enabled'
} elseif ($manualChallengeReportingSupported) {
  $args += '--manual-challenge-reporting'
}

& $ctx.Python @args
