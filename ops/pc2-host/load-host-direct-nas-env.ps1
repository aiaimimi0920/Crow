$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'crow-environment.ps1')

$root = 'C:\fapaifang-worker'
$srcRoot = Join-Path $root 'src'
$envFile = Join-Path $root 'env.worker.local'

Import-CrowOperatorEnvironment -Path $envFile

$sharedRoot = if ((Get-CrowEnvironmentValue -Name 'CROW_NAS_SHARE_ROOT' -PathValue)) { (Get-CrowEnvironmentValue -Name 'CROW_NAS_SHARE_ROOT' -PathValue) } else { '\\192.168.15.200\home\project\project\FPFData' }
$shareMount = if ((Get-CrowEnvironmentValue -Name 'CROW_NAS_SHARE_MOUNT' -PathValue)) { (Get-CrowEnvironmentValue -Name 'CROW_NAS_SHARE_MOUNT' -PathValue) } else { '\\192.168.15.200\home' }
$shareUser = [string]((Get-CrowEnvironmentValue -Name 'CROW_NAS_SHARE_USER'))
$sharePassword = [string]((Get-CrowEnvironmentValue -Name 'CROW_NAS_SHARE_PASSWORD'))
$listBrowserFallback = if ((Get-CrowEnvironmentValue -Name 'CROW_LIST_BROWSER_FALLBACK')) { (Get-CrowEnvironmentValue -Name 'CROW_LIST_BROWSER_FALLBACK') } else { '1' }
$detailBrowserFallback = if ((Get-CrowEnvironmentValue -Name 'CROW_DETAIL_BROWSER_FALLBACK')) { (Get-CrowEnvironmentValue -Name 'CROW_DETAIL_BROWSER_FALLBACK') } else { '1' }
$detailLoadOpenBrowserPages = if ((Get-CrowEnvironmentValue -Name 'CROW_DETAIL_LOAD_OPEN_BROWSER_PAGES')) { (Get-CrowEnvironmentValue -Name 'CROW_DETAIL_LOAD_OPEN_BROWSER_PAGES') } else { '0' }
$captchaSolverEnabled = if ((Get-CrowEnvironmentValue -Name 'CROW_CAPTCHA_SOLVER_ENABLED')) { (Get-CrowEnvironmentValue -Name 'CROW_CAPTCHA_SOLVER_ENABLED') } else { '1' }
$realTaobaoAutoSolverEnabled = if ((Get-CrowEnvironmentValue -Name 'CROW_REAL_TAOBAO_AUTO_SOLVER_ENABLED')) { (Get-CrowEnvironmentValue -Name 'CROW_REAL_TAOBAO_AUTO_SOLVER_ENABLED') } else { '0' }
$seedCaptchaSolverEnabled = if ((Get-CrowEnvironmentValue -Name 'CROW_SEED_CAPTCHA_SOLVER_ENABLED')) { (Get-CrowEnvironmentValue -Name 'CROW_SEED_CAPTCHA_SOLVER_ENABLED') } else { $captchaSolverEnabled }
$detailCaptchaSolverEnabled = if ((Get-CrowEnvironmentValue -Name 'CROW_DETAIL_CAPTCHA_SOLVER_ENABLED')) { (Get-CrowEnvironmentValue -Name 'CROW_DETAIL_CAPTCHA_SOLVER_ENABLED') } else { $captchaSolverEnabled }

if ($shareUser -and $sharePassword) {
  & cmd /c "cmdkey /add:192.168.15.200 /user:$shareUser /pass:$sharePassword >nul 2>nul" | Out-Null
  $netUseTarget = if ($shareMount -eq '\\192.168.15.200\home') { '\\192.168.15.200\home' } else { $shareMount }
  & cmd /c "net use \\192.168.15.200\home /user:$shareUser $sharePassword /persistent:yes >nul 2>nul" | Out-Null
  if ($netUseTarget -ne '\\192.168.15.200\home') {
    & cmd /c "net use $netUseTarget /user:$shareUser $sharePassword /persistent:yes >nul 2>nul" | Out-Null
  }
}

[Environment]::SetEnvironmentVariable('PYTHONIOENCODING', 'utf-8', 'Process')
(Set-CrowEnvironmentValue -Name 'CROW_DB_URL' -Value ('postgresql+psycopg://fapaifang:fapaifang@192.168.15.200:55432/fapaifang'))
(Set-CrowEnvironmentValue -Name 'CROW_DB_AUTO_CREATE' -Value ('0'))
(Set-CrowEnvironmentValue -Name 'CROW_DB_ENABLE_POSTGIS' -Value ('0'))
$cdpEndpoint = if ((Get-CrowEnvironmentValue -Name 'CROW_CDP_ENDPOINT')) {
  (Get-CrowEnvironmentValue -Name 'CROW_CDP_ENDPOINT')
} else {
  'http://127.0.0.1:9223'
}
$detailCdpEndpoint = if ((Get-CrowEnvironmentValue -Name 'CROW_DETAIL_CDP_ENDPOINT')) {
  (Get-CrowEnvironmentValue -Name 'CROW_DETAIL_CDP_ENDPOINT')
} else {
  $cdpEndpoint
}
(Set-CrowEnvironmentValue -Name 'CROW_CDP_ENDPOINT' -Value ($cdpEndpoint))
(Set-CrowEnvironmentValue -Name 'CROW_DETAIL_CDP_ENDPOINT' -Value ($detailCdpEndpoint))
(Set-CrowEnvironmentValue -Name 'CROW_LIST_BROWSER_FALLBACK' -Value ($listBrowserFallback))
(Set-CrowEnvironmentValue -Name 'CROW_DETAIL_BROWSER_FALLBACK' -Value ($detailBrowserFallback))
(Set-CrowEnvironmentValue -Name 'CROW_DETAIL_LOAD_OPEN_BROWSER_PAGES' -Value ($detailLoadOpenBrowserPages))
(Set-CrowEnvironmentValue -Name 'CROW_SHARED_DATA_ROOT_HOST' -Value ($sharedRoot))
(Set-CrowEnvironmentValue -Name 'CROW_API_BASE_URL' -Value ('http://192.168.15.200:8001/api'))
(Set-CrowEnvironmentValue -Name 'CROW_CENTRAL_API_BASE_URL' -Value ('http://192.168.15.200:8001/api'))
(Set-CrowEnvironmentValue -Name 'CROW_NODE_ID' -Value ('pc2'))
$reportCdpEndpoint = if ((Get-CrowEnvironmentValue -Name 'CROW_REPORT_CDP_ENDPOINT')) { (Get-CrowEnvironmentValue -Name 'CROW_REPORT_CDP_ENDPOINT') } else { 'http://192.168.15.104:9224' }
(Set-CrowEnvironmentValue -Name 'CROW_REPORT_CDP_ENDPOINT' -Value ($reportCdpEndpoint))
(Set-CrowEnvironmentValue -Name 'CROW_COOKIE_SNAPSHOT' -Value ((Join-Path $sharedRoot 'secrets\nodes\pc2\taobao-cookies.json')))
$cookieSnapshotPrefer = if ((Get-CrowEnvironmentValue -Name 'CROW_COOKIE_SNAPSHOT_PREFER')) { (Get-CrowEnvironmentValue -Name 'CROW_COOKIE_SNAPSHOT_PREFER') } else { '0' }
(Set-CrowEnvironmentValue -Name 'CROW_COOKIE_SNAPSHOT_PREFER' -Value ($cookieSnapshotPrefer))
(Set-CrowEnvironmentValue -Name 'CROW_CAPTCHA_SOLVER_ENABLED' -Value ($captchaSolverEnabled))
(Set-CrowEnvironmentValue -Name 'CROW_REAL_TAOBAO_AUTO_SOLVER_ENABLED' -Value ($realTaobaoAutoSolverEnabled))
(Set-CrowEnvironmentValue -Name 'CROW_SEED_CAPTCHA_SOLVER_ENABLED' -Value ($seedCaptchaSolverEnabled))
(Set-CrowEnvironmentValue -Name 'CROW_DETAIL_CAPTCHA_SOLVER_ENABLED' -Value ($detailCaptchaSolverEnabled))
(Set-CrowEnvironmentValue -Name 'CROW_SEED_JOBS_FILE' -Value ((Join-Path $sharedRoot 'jobs\seed_jobs_all.json')))

$srcSecrets = Join-Path $srcRoot 'secrets.json'
$nestedSecrets = Join-Path $srcRoot 'src\secrets.json'

if ((Test-Path $srcSecrets) -and -not (Test-Path $nestedSecrets)) {
  New-Item -ItemType Directory -Force -Path (Join-Path $srcRoot 'src') | Out-Null
  Copy-Item $srcSecrets $nestedSecrets -Force
}

[pscustomobject]@{
  Root = $root
  SrcRoot = $srcRoot
  SharedRoot = $sharedRoot
  Python = 'C:\fapaifang-worker\venv-host\Scripts\python.exe'
}
