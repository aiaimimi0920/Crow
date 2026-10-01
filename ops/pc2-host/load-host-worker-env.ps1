$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'crow-environment.ps1')

$root = 'C:\fapaifang-worker'
$srcRoot = Join-Path $root 'src'
$sharedRoot = 'C:\Users\Public\nas_home\AI\FPFData'
$envFile = Join-Path $root 'env.worker.local'

Import-CrowOperatorEnvironment -Path $envFile

[Environment]::SetEnvironmentVariable('PYTHONIOENCODING', 'utf-8', 'Process')
(Set-CrowEnvironmentValue -Name 'CROW_DB_URL' -Value ('postgresql+psycopg://fapaifang:fapaifang@192.168.15.200:55432/fapaifang'))
(Set-CrowEnvironmentValue -Name 'CROW_DB_AUTO_CREATE' -Value ('0'))
(Set-CrowEnvironmentValue -Name 'CROW_DB_ENABLE_POSTGIS' -Value ('0'))
(Set-CrowEnvironmentValue -Name 'CROW_CDP_ENDPOINT' -Value ('http://127.0.0.1:9223'))
(Set-CrowEnvironmentValue -Name 'CROW_DETAIL_LOAD_OPEN_BROWSER_PAGES' -Value ('0'))
(Set-CrowEnvironmentValue -Name 'CROW_SHARED_DATA_ROOT_HOST' -Value ($sharedRoot))
(Set-CrowEnvironmentValue -Name 'CROW_API_BASE_URL' -Value ('http://192.168.15.200:8001/api'))
(Set-CrowEnvironmentValue -Name 'CROW_CENTRAL_API_BASE_URL' -Value ('http://192.168.15.200:8001/api'))
(Set-CrowEnvironmentValue -Name 'CROW_NODE_ID' -Value ('pc2'))
(Set-CrowEnvironmentValue -Name 'CROW_REPORT_CDP_ENDPOINT' -Value ('http://192.168.15.104:9224'))
(Set-CrowEnvironmentValue -Name 'CROW_COOKIE_SNAPSHOT' -Value ((Join-Path $sharedRoot 'secrets\nodes\pc2\taobao-cookies.json')))
(Set-CrowEnvironmentValue -Name 'CROW_COOKIE_SNAPSHOT_PREFER' -Value ('0'))
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
