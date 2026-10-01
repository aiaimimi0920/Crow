param(
  [string]$EnvFile = 'C:\fapaifang-worker\env.worker.local',
  [string]$SnapshotPath = '\\192.168.15.200\home\project\project\FPFData\secrets\nodes\pc2\taobao-cookies.json'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'crow-environment.ps1')

if (-not (Test-Path -LiteralPath $EnvFile)) {
  throw "PC2 worker environment file does not exist: $EnvFile"
}
$nasLoader = 'C:\fapaifang-worker\ops\load-host-direct-nas-env.ps1'
if (-not (Test-Path -LiteralPath $nasLoader)) {
  throw "PC2 NAS environment loader does not exist."
}
$null = & $nasLoader
if (-not (Test-Path -LiteralPath $SnapshotPath)) {
  throw "PC2 cookie snapshot does not exist on the NAS."
}

$required = [ordered]@{
  CROW_LIST_BROWSER_FALLBACK = '0'
  CROW_DETAIL_BROWSER_FALLBACK = '0'
  CROW_DETAIL_LOAD_OPEN_BROWSER_PAGES = '0'
  CROW_COOKIE_SNAPSHOT_PREFER = '1'
  CROW_CAPTCHA_SOLVER_ENABLED = '0'
  CROW_COOKIE_SNAPSHOT = $SnapshotPath
  CROW_HOST_DETAIL_WORKER_COUNT = '4'
  CROW_HOST_ANALYSIS_WORKER_COUNT = '4'
}
$compatibleRequired = [ordered]@{}
foreach ($entry in $required.GetEnumerator()) {
  foreach ($name in @(Get-CrowEnvironmentNames -Name $entry.Key)) {
    $compatibleRequired[$name] = $entry.Value
  }
}
$required = $compatibleRequired
$seen = @{}
$lines = foreach ($line in [System.IO.File]::ReadAllLines($EnvFile, [System.Text.Encoding]::UTF8)) {
  $separator = $line.IndexOf('=')
  if ($separator -lt 1 -or $line.TrimStart().StartsWith('#')) {
    $line
    continue
  }
  $name = $line.Substring(0, $separator).Trim()
  if ($required.Contains($name)) {
    $seen[$name] = $true
    '{0}={1}' -f $name, $required[$name]
  } else {
    $line
  }
}
foreach ($entry in $required.GetEnumerator()) {
  if (-not $seen.ContainsKey($entry.Key)) {
    $lines += '{0}={1}' -f $entry.Key, $entry.Value
  }
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($EnvFile, $lines, $utf8NoBom)

[pscustomobject]@{
  mode = 'pc2_cookie_http_only'
  list_browser_fallback = 0
  detail_browser_fallback = 0
  detail_load_open_browser_pages = 0
  cookie_snapshot_prefer = 1
  captcha_solver_enabled = 0
  detail_worker_count = 4
  analysis_worker_count = 4
  snapshot_exists = $true
} | ConvertTo-Json -Compress
