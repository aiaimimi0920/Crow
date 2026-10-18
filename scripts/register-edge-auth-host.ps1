param(
    [string]$InstallRoot = (Split-Path -Parent $PSScriptRoot),
    [ValidateSet('CurrentUser', 'LocalMachine')]
    [string]$RegistrationScope = 'CurrentUser'
)
$ErrorActionPreference = 'Stop'
if ($RegistrationScope -eq 'LocalMachine') {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'LocalMachine registration requires an elevated PowerShell. The native host itself must not run elevated.'
    }
}
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).ProviderPath
. (Join-Path $InstallRoot 'scripts/project-environment.ps1')
$config = [IO.File]::ReadAllText((Join-Path $InstallRoot 'crow-desktop.runtime.json')) | ConvertFrom-Json
$python = Get-CrowEnvironmentValue -Name 'CROW_DESKTOP_PYTHON_PATH' -Environment (ConvertTo-CrowEnvironmentMap -Value $config.environment) -PathValue
if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Configured Python is unavailable.' }
if ($python -match '[%\r\n"]' -or $InstallRoot -match '[%\r\n"]') { throw 'Unsupported launcher path.' }
$directory = Join-Path $InstallRoot 'edge-native'
$manifest = Join-Path $directory 'com.crow.manual_auth.json'
$registryPath = 'Software\Microsoft\Edge\NativeMessagingHosts\com.crow.manual_auth'
$hive = [Microsoft.Win32.RegistryHive]::$RegistrationScope
$base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, [Microsoft.Win32.RegistryView]::Registry64)
try {
    $existing = $base.OpenSubKey($registryPath)
    if ($existing) {
        try {
            if ([string]$existing.GetValue('') -ne $manifest) {
                throw 'Existing Crow native host points to another installation; explicit migration is required.'
            }
        } finally { $existing.Dispose() }
    }
} finally { $base.Dispose() }
[IO.Directory]::CreateDirectory($directory) | Out-Null
$utf8 = New-Object Text.UTF8Encoding($false)
$launcher = Join-Path $directory 'crow-edge-auth.cmd'
$hostScript = Join-Path $InstallRoot 'tools/edge_auth_host.py'
$text = "@echo off`r`nset PYTHONUTF8=1`r`n`"$python`" -I `"$hostScript`" %*`r`n"
[IO.File]::WriteAllText($launcher, $text, $utf8)
$value = @{ name = 'com.crow.manual_auth'; description = 'Crow explicit manual authentication';
    path = $launcher; type = 'stdio'; allowed_origins = @('chrome-extension://hkpcgieobdbcophagofgeglpiofmedhg/') }
[IO.File]::WriteAllText($manifest, ($value | ConvertTo-Json -Depth 4), $utf8)
$base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, [Microsoft.Win32.RegistryView]::Registry64)
try {
    $key = $base.CreateSubKey($registryPath)
    try {
        $key.SetValue('', $manifest, [Microsoft.Win32.RegistryValueKind]::String)
        $key.Flush()
        if ($key.GetValue('') -ne $manifest) { throw 'Native host registration verification failed.' }
    } finally { $key.Dispose() }
} finally { $base.Dispose() }
Write-Output "Registered Crow Edge native host ($RegistrationScope, Registry64): $manifest"
Write-Output "Load unpacked extension in the intended Edge profile: $(Join-Path $InstallRoot 'browser-extension/crow-auth')"
