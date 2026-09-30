param(
  [string]$RequestedWorkerId = '',
  [string]$RequestedOutputDir = ''
)
. (Join-Path $PSScriptRoot 'crow-environment.ps1')


$ctx = & 'C:\fapaifang-worker\ops\load-host-direct-nas-env.ps1'
Set-Location $ctx.SrcRoot

$workerId = if ($RequestedWorkerId) {
  $RequestedWorkerId
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_HOST_ANALYSIS_WORKER_ID')) {
  (Get-CrowEnvironmentValue -Name 'CROW_HOST_ANALYSIS_WORKER_ID')
} else {
  'pc2-real-analysis-1'
}
$outputDir = if ($RequestedOutputDir) {
  $RequestedOutputDir
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_HOST_ANALYSIS_OUTPUT_DIR' -PathValue)) {
  (Get-CrowEnvironmentValue -Name 'CROW_HOST_ANALYSIS_OUTPUT_DIR' -PathValue)
} else {
  Join-Path $ctx.SharedRoot 'output\nodes\pc2-real\detail_analysis_worker'
}
$targetSuccess = if ((Get-CrowEnvironmentValue -Name 'CROW_HOST_ANALYSIS_TARGET_SUCCESS')) {
  (Get-CrowEnvironmentValue -Name 'CROW_HOST_ANALYSIS_TARGET_SUCCESS')
} else {
  '2'
}
$maxAttempts = if ((Get-CrowEnvironmentValue -Name 'CROW_HOST_ANALYSIS_MAX_ATTEMPTS')) {
  (Get-CrowEnvironmentValue -Name 'CROW_HOST_ANALYSIS_MAX_ATTEMPTS')
} else {
  '3'
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
  Write-Output "analysis already running with pid $($existing.ProcessId)"
  exit 0
}

$openAiBaseUrl = if ($env:OPENAI_BASE_URL) {
  $env:OPENAI_BASE_URL
} elseif ($env:OPENAI_API_BASE) {
  $env:OPENAI_API_BASE
} else {
  $env:OPENAI_COMPATIBLE_BASE_URL
}
if (-not $openAiBaseUrl -or -not $env:OPENAI_API_KEY) {
  throw 'PC2 analysis worker requires a configured OpenAI-compatible base URL and API key.'
}

$args = @(
  'tools\detail_worker.py',
  '--analysis-only',
  '--output-dir', $outputDir,
  '--target-success', $targetSuccess,
  '--max-attempts', $maxAttempts,
  '--item-max-attempts', '3',
  '--lease-seconds', '900',
  '--worker-id', $workerId,
  '--failure-cooldown-seconds', '120',
  '--loop',
  '--active-loop-interval-seconds', '5',
  '--loop-interval-seconds', '30',
  '--api-base-url', 'http://192.168.15.200:8001/api',
  '--llm-preflight',
  '--llm-preflight-timeout-seconds', '30'
)

& $ctx.Python @args
