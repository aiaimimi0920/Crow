param(
  [string]$SourceEnvPath = '\\192.168.15.200\home\project\project\fapaifang\docker.local.env'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'crow-environment.ps1')

$root = 'C:\fapaifang-worker'
$envPath = Join-Path $root 'env.worker.local'
$loaderPath = Join-Path $root 'ops\load-host-direct-nas-env.ps1'
$allowedSourceRoot = '\\192.168.15.200\home\project\project\fapaifang'
$allowedNames = @(
  'OPENAI_BASE_URL',
  'OPENAI_API_BASE',
  'OPENAI_COMPATIBLE_BASE_URL',
  'OPENAI_API_KEY',
  'OPENAI_MODEL',
  'OPENAI_COMPATIBLE_MODEL',
  'OPENAI_MODEL_CANDIDATES',
  'OPENAI_REASONING_EFFORT',
  'OPENAI_TIMEOUT_SECONDS',
  'OPENAI_MAX_RETRIES',
  'OPENAI_PROXY',
  'CROW_LLM_PROXY',
  'FAPAI_LLM_PROXY',
  'OPENAI_HTTP_PROXY',
  'OPENAI_HTTPS_PROXY',
  'CROW_LLM_HTTP_PROXY',
  'FAPAI_LLM_HTTP_PROXY',
  'CROW_LLM_HTTPS_PROXY',
  'FAPAI_LLM_HTTPS_PROXY'
)

if (-not (Test-Path -LiteralPath $loaderPath)) {
  throw "Missing PC2 environment loader: $loaderPath"
}
$ctx = & $loaderPath

$resolvedSource = [IO.Path]::GetFullPath($SourceEnvPath)
$resolvedAllowedRoot = [IO.Path]::GetFullPath($allowedSourceRoot).TrimEnd('\')
if (-not $resolvedSource.StartsWith("$resolvedAllowedRoot\", [StringComparison]::OrdinalIgnoreCase)) {
  throw 'Analysis environment source must stay inside the approved project share.'
}
if (-not (Test-Path -LiteralPath $resolvedSource)) {
  throw "Analysis environment source does not exist: $resolvedSource"
}
if (-not (Test-Path -LiteralPath $envPath)) {
  throw "PC2 worker environment does not exist: $envPath"
}

$updates = @{}
Get-Content -LiteralPath $resolvedSource -Encoding UTF8 | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith('#')) {
    return
  }
  $separator = $line.IndexOf('=')
  if ($separator -lt 1) {
    return
  }
  $name = $line.Substring(0, $separator).Trim()
  $value = $line.Substring($separator + 1)
  if ($allowedNames -contains $name -and $value) {
    $updates[$name] = $value
  }
}

# Resolve only the approved proxy groups, before backup or destination writes.
foreach ($name in @('CROW_LLM_PROXY', 'CROW_LLM_HTTP_PROXY', 'CROW_LLM_HTTPS_PROXY')) {
  $value = Get-CrowEnvironmentValue -Name $name -Environment $updates
  if ($null -ne $value) { Set-CrowEnvironmentValue -Name $name -Value $value -Environment $updates }
}

$hasBaseUrl = @(
  @(
    'OPENAI_BASE_URL',
    'OPENAI_API_BASE',
    'OPENAI_COMPATIBLE_BASE_URL'
  ) | Where-Object { $updates.ContainsKey($_) }
)
if (-not $updates.ContainsKey('OPENAI_API_KEY') -or $hasBaseUrl.Count -eq 0) {
  throw 'Approved source is missing required OpenAI-compatible settings.'
}

$backupDir = Join-Path $root ('backups\analysis-enable-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
Copy-Item -LiteralPath $envPath -Destination (Join-Path $backupDir 'env.worker.local') -Force

$lines = [System.Collections.Generic.List[string]]@(Get-Content -LiteralPath $envPath -Encoding UTF8)
$staleAllowedNames = @($allowedNames | Where-Object { -not $updates.ContainsKey($_) })
$removedStaleSettingCount = 0
for ($index = $lines.Count - 1; $index -ge 0; $index--) {
  foreach ($name in $staleAllowedNames) {
    if ($lines[$index] -match ('^\s*' + [regex]::Escape($name) + '=')) {
      $lines.RemoveAt($index)
      $removedStaleSettingCount += 1
      break
    }
  }
}
foreach ($name in $updates.Keys) {
  $found = $false
  for ($index = 0; $index -lt $lines.Count; $index++) {
    if ($lines[$index] -match ('^\s*' + [regex]::Escape($name) + '=')) {
      $lines[$index] = "$name=$($updates[$name])"
      $found = $true
    }
  }
  if (-not $found) {
    $lines.Add("$name=$($updates[$name])")
  }
}

[IO.File]::WriteAllLines($envPath, $lines, (New-Object Text.UTF8Encoding($false)))

[pscustomobject]@{
  imported_setting_count = $updates.Count
  removed_stale_setting_count = $removedStaleSettingCount
  backup_created = Test-Path -LiteralPath (Join-Path $backupDir 'env.worker.local')
  source_within_approved_root = $true
  openai_base_url_configured = [bool]$hasBaseUrl.Count
  openai_api_key_configured = $updates.ContainsKey('OPENAI_API_KEY')
  openai_model_configured = $updates.ContainsKey('OPENAI_MODEL') -or $updates.ContainsKey('OPENAI_COMPATIBLE_MODEL')
  shared_root_reachable = Test-Path -LiteralPath $ctx.SharedRoot
} | ConvertTo-Json -Compress
