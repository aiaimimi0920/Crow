. (Join-Path $PSScriptRoot 'crow-environment.ps1')
$ctx = & 'C:\fapaifang-worker\ops\load-host-worker-env.ps1'
Set-Location $ctx.SrcRoot
$outputDir = Join-Path $ctx.SharedRoot 'output\nodes\pc2-host\detail_worker'
$workerId = if ((Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_WORKER_ID')) { (Get-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_WORKER_ID') } else { 'pc2-host-detail-1' }

$args = @(
  'tools\detail_worker.py',
  '--output-dir', $outputDir,
  '--cdp-endpoint', 'http://127.0.0.1:9223',
  '--target-success', '2',
  '--max-attempts', '6',
  '--item-max-attempts', '3',
  '--worker-id', $workerId,
  '--failure-cooldown-seconds', '120',
  '--loop',
  '--active-loop-interval-seconds', '10',
  '--loop-interval-seconds', '60',
  '--api-base-url', 'http://192.168.15.200:8001/api',
  '--raw-only',
  '--solver-enabled'
)

& $ctx.Python @args
