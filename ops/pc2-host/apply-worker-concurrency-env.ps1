param(
  [string]$EnvFile = 'C:\fapaifang-worker\env.worker.local',
  [ValidateRange(3, 8)][int]$DetailWorkerCount = 4,
  [ValidateRange(3, 8)][int]$AnalysisWorkerCount = 4
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'crow-environment.ps1')

if (-not (Test-Path -LiteralPath $EnvFile)) {
  throw "PC2 worker environment file does not exist: $EnvFile"
}

$required = [ordered]@{
  CROW_HOST_DETAIL_WORKER_COUNT = [string]$DetailWorkerCount
  CROW_HOST_ANALYSIS_WORKER_COUNT = [string]$AnalysisWorkerCount
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
  detail_worker_count = $DetailWorkerCount
  analysis_worker_count = $AnalysisWorkerCount
  unrelated_settings_preserved = $true
} | ConvertTo-Json -Compress
