param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [string]$ApiBase = "",
    [string]$CookieSnapshotPath = '',
    [string]$RecoveryTokenPath = '',
    [ValidateRange(1024, 65535)][int]$AuthLocalCdpPort = 9225,
    [string]$AuthBrowserProfileDir = '',
    [string]$AuthBrowserPath = '',
    [string]$SettingsApiBase = '',
    [string]$SettingsCaFile = '',
    [string]$ApiCaFile = '',
    [string]$OperatorTokenFile = ''
)
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'project-environment.ps1')
if (-not $PSBoundParameters.ContainsKey('ApiBase')) { $ApiBase = (Get-CrowEnvironmentValue -Name 'CROW_COLLECTOR_API_BASE') }


. (Join-Path $PSScriptRoot 'collection-api-origin.ps1')
$root = [IO.Path]::GetFullPath($InstallRoot)
if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'Install root must exist' }
$path = Join-Path $root 'crow-desktop.runtime.json'
if (Test-Path -LiteralPath $path) {
    $previous = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) | ConvertFrom-Json
    $saved = ConvertTo-CrowEnvironmentMap -Value $previous.environment
    if (-not $ApiBase) { $ApiBase = (Get-CrowEnvironmentValue -Name 'CROW_COLLECTOR_API_BASE' -Environment $saved) }
    if (-not $SettingsApiBase) { $SettingsApiBase = (Get-CrowEnvironmentValue -Name 'CROW_SETTINGS_API_BASE' -Environment $saved) }
    if (-not $SettingsCaFile) { $SettingsCaFile = (Get-CrowEnvironmentValue -Name 'CROW_SETTINGS_CA_FILE' -Environment $saved -PathValue) }
    if (-not $ApiCaFile) { $ApiCaFile = (Get-CrowEnvironmentValue -Name 'CROW_API_CA_FILE' -Environment $saved -PathValue) }
    if (-not $OperatorTokenFile) { $OperatorTokenFile = (Get-CrowEnvironmentValue -Name 'CROW_ENGINE_OPERATOR_TOKEN_FILE' -Environment $saved -PathValue) }
}
$ApiBase = ConvertTo-CollectionApiOrigin -ApiBase $ApiBase
$data = [IO.Path]::GetFullPath($DataRoot)
$pythonResolver = Join-Path $PSScriptRoot 'resolve-pc1-auth-python.ps1'
if (-not (Test-Path -LiteralPath $pythonResolver -PathType Leaf)) { throw 'PC1 auth Python resolver is missing' }
. $pythonResolver
$resolvedPython = Resolve-Pc1AuthPython
$values = [ordered]@{
    CROW_COLLECTOR_API_BASE = $ApiBase
    CROW_DATA_ROOT_HOST = $data
    CROW_COOKIE_SNAPSHOT = $(if ($CookieSnapshotPath) { [IO.Path]::GetFullPath($CookieSnapshotPath) } else { Join-Path $data 'secrets\nodes\pc2\taobao-cookies.json' })
    CROW_NAS_AUTH_RECOVERY_TOKEN_FILE = $(if ($RecoveryTokenPath) { [IO.Path]::GetFullPath($RecoveryTokenPath) } else { Join-Path $data 'secrets\nas-auth-recovery.token' })
    CROW_AUTH_LOCAL_CDP_PORT = [string]$AuthLocalCdpPort
    CROW_DESKTOP_PYTHON_PATH = $resolvedPython
}
if ($AuthBrowserProfileDir) { $values.CROW_AUTH_BROWSER_PROFILE_DIR = [IO.Path]::GetFullPath($AuthBrowserProfileDir) }
if ($AuthBrowserPath) { $values.CROW_AUTH_BROWSER_PATH = [IO.Path]::GetFullPath($AuthBrowserPath) }
if ($SettingsApiBase -or $SettingsCaFile -or $OperatorTokenFile) {
    $control = [uri]$SettingsApiBase
    if (-not $control.IsAbsoluteUri -or $control.Scheme -ne 'https' -or $control.UserInfo -or $control.Query -or $control.Fragment -or $control.AbsolutePath -ne '/' -or -not $SettingsCaFile -or -not $OperatorTokenFile) {
        throw 'Settings requires an HTTPS origin, application CA file and operator token file'
    }
    $settingsCaPath = [IO.Path]::GetFullPath($SettingsCaFile)
    $operatorTokenPath = [IO.Path]::GetFullPath($OperatorTokenFile)
    if (-not (Test-Path -LiteralPath $settingsCaPath -PathType Leaf)) {
        throw 'Settings API CA file is unavailable.'
    }
    if (-not (Test-Path -LiteralPath $operatorTokenPath -PathType Leaf)) {
        throw 'Settings operator token file is unavailable.'
    }
    $values.CROW_SETTINGS_API_BASE = $SettingsApiBase
    $values.CROW_SETTINGS_CA_FILE = $settingsCaPath
    $values.CROW_ENGINE_OPERATOR_TOKEN_FILE = $operatorTokenPath
}
if ($ApiCaFile) {
    $apiCaPath = [IO.Path]::GetFullPath($ApiCaFile)
    if (-not (Test-Path -LiteralPath $apiCaPath -PathType Leaf)) {
        throw 'Collection API CA file is unavailable.'
    }
    $values.CROW_API_CA_FILE = $apiCaPath
}
foreach ($key in @($values.Keys)) { Set-CrowEnvironmentValue -Name $key -Value $values[$key] -Environment $values }
$json = [ordered]@{ version = 1; environment = $values } | ConvertTo-Json -Depth 3
$temporary = Join-Path $root ('.desktop-config-' + [guid]::NewGuid().ToString('N') + '.tmp')
try {
    [IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $path) { [IO.File]::Replace($temporary, $path, [NullString]::Value) }
    else { [IO.File]::Move($temporary, $path) }
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
}
Write-Output 'Non-secret desktop runtime configuration saved.'
