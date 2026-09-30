param(
  [string]$ApiBaseUrl = 'http://192.168.15.200:8001/api',
  [string]$CdpEndpoint = 'http://127.0.0.1:9223',
  [string]$NodeId = 'pc2'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'crow-environment.ps1')

$root = 'C:\fapaifang-worker'
$sourceRoot = Join-Path $root 'src'
$envFile = Join-Path $root 'env.worker.local'
$python = Join-Path $root 'venv-host\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  $python = 'C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe'
}

$solverRuntimeDefaults = [ordered]@{
  CROW_REAL_TAOBAO_AUTO_SOLVER_ENABLED = '0'
  CROW_SOLVER_COOLDOWN_FAIL_THRESHOLD = '10'
  CROW_SOLVER_COOLDOWN_SECONDS = '180'
  CROW_SLIDER_RETRY_INTERVAL_SECONDS = '5'
  CROW_LOCAL_SOLVER_POLL_SECONDS = '5'
}
foreach ($name in $solverRuntimeDefaults.Keys) {
  $value = (Get-CrowEnvironmentValue -Name $name)
  if (-not $value -and (Test-Path -LiteralPath $envFile)) {
    $settings = Read-CrowOperatorEnvironment -Path $envFile
    $value = (Get-CrowEnvironmentValue -Name $name -Environment $settings)
    if ($null -ne $value) { $value = $value.Trim() }
  }
  if (-not $value) {
    $value = $solverRuntimeDefaults[$name]
  }
  Set-CrowEnvironmentValue -Name $name -Value $value
}

(Set-CrowEnvironmentValue -Name 'CROW_API_BASE_URL' -Value ($ApiBaseUrl))
(Set-CrowEnvironmentValue -Name 'CROW_CDP_ENDPOINT' -Value ($CdpEndpoint))
(Set-CrowEnvironmentValue -Name 'CROW_NODE_ID' -Value ($NodeId))
[Environment]::SetEnvironmentVariable('PYTHONUNBUFFERED', '1', 'Process')

Set-Location -LiteralPath $sourceRoot
& $python '.\tools\pc2_local_solver.py' `
  --api-base-url $ApiBaseUrl `
  --cdp-endpoint $CdpEndpoint `
  --node-id $NodeId
exit $LASTEXITCODE
