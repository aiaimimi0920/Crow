param(
    [string]$InstallRoot = "",
    [string]$BuildTargetRoot = "",
    [string]$DesktopDirectory = [Environment]::GetFolderPath('Desktop'),
    [string]$ApiBase = $env:FAPAI_COLLECTOR_API_BASE,
    [string]$ApiCaFile = "",
    [string]$SettingsApiBase = "",
    [string]$SettingsCaFile = "",
    [string]$OperatorTokenFile = "",
    [string]$RemoteAuthHost = "192.168.15.104",
    [string]$RemoteAuthUser = "Admin",
    [string]$RemoteAuthPassword = "",
    [string]$RemoteAuthKeyPath = "",
    [string]$DataRoot = "",
    [string]$CookieSnapshotPath = "",
    [ValidateSet("remote", "local-bridge")][string]$AuthBrowserMode = "local-bridge",
    [int]$AuthLocalCdpPort = 9225,
    [int]$AuthRemoteCdpPort = 9225,
    [string]$AuthBrowserProfileDir = "",
    [string]$AuthBrowserPath = "C:\Program Files\Google\Chrome\Application\chrome.exe",
    [switch]$SkipBuild,
    [switch]$SkipLaunch,
    [switch]$SkipShortcut
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Resolve-RepoRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
}

function Invoke-CmdInLocalWorkingDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Command
    )

    Push-Location $env:SystemRoot
    try {
        & cmd /d /c $Command
    }
    finally {
        Pop-Location
    }
}

function Invoke-CollectorDesktopBuild {
    param(
        [Parameter(Mandatory = $true)][string]$CollectorRoot,
        [Parameter(Mandatory = $true)][string]$TargetRoot
    )

    New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null

    $previousCargoTargetDir = $env:CARGO_TARGET_DIR
    $env:CARGO_TARGET_DIR = $TargetRoot
    try {
        $installCommand = "pushd `"$CollectorRoot`" && if not exist node_modules npm install && popd"
        Invoke-CmdInLocalWorkingDirectory -Command $installCommand
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed with exit code $LASTEXITCODE"
        }

        $buildCommand = "pushd `"$CollectorRoot`" && npm run tauri:build && popd"
        Invoke-CmdInLocalWorkingDirectory -Command $buildCommand
        if ($LASTEXITCODE -ne 0) {
            throw "npm run tauri:build failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        if ($null -eq $previousCargoTargetDir) {
            Remove-Item Env:\CARGO_TARGET_DIR -ErrorAction SilentlyContinue
        }
        else {
            $env:CARGO_TARGET_DIR = $previousCargoTargetDir
        }
    }
}

function Backup-ExistingInstall {
    param(
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )

    if (-not (Test-Path -LiteralPath $DestinationRoot)) {
        return
    }

    $backupRoot = Join-Path $DestinationRoot "backup"
    $timestamp = (Get-Date -Format "yyyyMMdd-HHmmss") + '-' + [Guid]::NewGuid().ToString('N')
    $backupDir = Join-Path $backupRoot $timestamp
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

    foreach ($relativePath in @(
            "fapaifang_collector_desktop.exe",
            "start-fapaifang-collector.ps1",
            "crow-desktop.runtime.json",
            "scripts",
            "tools",
            "src"
        )) {
        $sourcePath = Join-Path $DestinationRoot $relativePath
        if (-not (Test-Path -LiteralPath $sourcePath)) {
            continue
        }
        $backupPath = Join-Path $backupDir $relativePath
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupPath) | Out-Null
        Copy-Item -LiteralPath $sourcePath -Destination $backupPath -Recurse -Force
    }

    # Deployment never deletes prior backups or organized runtime data.
}

function Stop-ExistingCollectorDesktop {
    $running = @(Get-Process -Name "fapaifang_collector_desktop" -ErrorAction SilentlyContinue)
    foreach ($process in $running) {
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "Could not stop collector desktop process $($process.Id): $($_.Exception.Message)"
        }
    }
}

function Copy-BundleFile {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$DestinationRoot,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    $sourcePath = Join-Path $SourceRoot $RelativePath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Missing bundle file: $sourcePath"
    }

    $destinationPath = Join-Path $DestinationRoot $RelativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destinationPath) | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
}

function Write-LauncherScript {
    param(
        [Parameter(Mandatory = $true)][string]$LauncherPath,
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [Parameter(Mandatory = $true)][string]$ApiBaseUrl,
        [Parameter(Mandatory = $true)][string]$RemoteHost,
        [Parameter(Mandatory = $true)][string]$RemoteUserName,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$RemotePasswordValue,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$RemoteKeyPath,
        [Parameter(Mandatory = $true)][string]$DataRootValue,
        [Parameter(Mandatory = $true)][string]$CookieSnapshotValue,
        [Parameter(Mandatory = $true)][string]$AuthBrowserModeValue,
        [Parameter(Mandatory = $true)][int]$AuthLocalCdpPortValue,
        [Parameter(Mandatory = $true)][int]$AuthRemoteCdpPortValue,
        [Parameter(Mandatory = $true)][string]$AuthBrowserProfileDirValue,
        [Parameter(Mandatory = $true)][string]$AuthBrowserPathValue
    )

    $launcherLines = New-Object System.Collections.Generic.List[string]
    if ($ApiBaseUrl) {
        $launcherLines.Add(('$env:FAPAI_COLLECTOR_API_BASE = ''{0}''' -f $ApiBaseUrl.Replace("'", "''")))
    }
    if ($RemoteHost) {
        $launcherLines.Add(('$env:FAPAI_REMOTE_AUTH_HOST = ''{0}''' -f $RemoteHost.Replace("'", "''")))
    }
    if ($RemoteUserName) {
        $launcherLines.Add(('$env:FAPAI_REMOTE_AUTH_USER = ''{0}''' -f $RemoteUserName.Replace("'", "''")))
    }
    if ($RemotePasswordValue) {
        $credentialPath = Join-Path (Split-Path -Parent $LauncherPath) ("secrets\remote-auth-{0}.dpapi" -f [Guid]::NewGuid().ToString('N'))
        $protected = ConvertTo-SecureString -String $RemotePasswordValue -AsPlainText -Force | ConvertFrom-SecureString
        Write-Utf8NoBomFile -Path $credentialPath -Content $protected
        $launcherLines.Add(('$protectedPassword = [IO.File]::ReadAllText(''{0}'') | ConvertTo-SecureString' -f $credentialPath.Replace("'", "''")))
        $launcherLines.Add('$env:FAPAI_REMOTE_AUTH_PASSWORD = ([pscredential]::new(''remote-auth'', $protectedPassword)).GetNetworkCredential().Password')
        $launcherLines.Add('$protectedPassword.Dispose()')
    }
    if ($RemoteKeyPath) {
        $launcherLines.Add(('$env:FAPAI_REMOTE_AUTH_KEY_PATH = ''{0}''' -f $RemoteKeyPath.Replace("'", "''")))
    }
    if ($DataRootValue) {
        $launcherLines.Add(('$env:FAPAI_DATA_ROOT_HOST = ''{0}''' -f $DataRootValue.Replace("'", "''")))
    }
    if ($CookieSnapshotValue) {
        $launcherLines.Add(('$env:FAPAI_COOKIE_SNAPSHOT = ''{0}''' -f $CookieSnapshotValue.Replace("'", "''")))
    }
    if ($AuthBrowserModeValue) {
        $launcherLines.Add(('$env:FAPAI_AUTH_BROWSER_MODE = ''{0}''' -f $AuthBrowserModeValue.Replace("'", "''")))
    }
    $launcherLines.Add(('$env:FAPAI_AUTH_LOCAL_CDP_PORT = ''{0}''' -f $AuthLocalCdpPortValue))
    $launcherLines.Add(('$env:FAPAI_AUTH_REMOTE_CDP_PORT = ''{0}''' -f $AuthRemoteCdpPortValue))
    if ($AuthBrowserProfileDirValue) {
        $launcherLines.Add(('$env:FAPAI_AUTH_BROWSER_PROFILE_DIR = ''{0}''' -f $AuthBrowserProfileDirValue.Replace("'", "''")))
    }
    if ($AuthBrowserPathValue) {
        $launcherLines.Add(('$env:FAPAI_AUTH_BROWSER_PATH = ''{0}''' -f $AuthBrowserPathValue.Replace("'", "''")))
    }
    $launcherLines.Add(('Start-Process -FilePath ''{0}''' -f $ExecutablePath.Replace("'", "''")))

    Write-Utf8NoBomFile -Path $LauncherPath -Content ($launcherLines -join [Environment]::NewLine)
}

function Resolve-RemoteAuthKeyPath {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        return $ExplicitPath
    }

    foreach ($candidate in @(
            (Join-Path $HOME ".ssh\id_ed25519"),
            (Join-Path $HOME ".ssh\id_rsa")
        )) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).ProviderPath
        }
    }

    return ""
}
$repoRoot = Resolve-RepoRoot
$collectorRoot = Join-Path $repoRoot "collector-desktop"
$deployRoot = if ($InstallRoot) {
    $InstallRoot
}
else {
    Join-Path $env:LOCALAPPDATA "FapaiFangCollectorDesktop"
}
$resolvedBuildTargetRoot = if ($BuildTargetRoot) {
    $BuildTargetRoot
}
else {
    Join-Path $env:TEMP "fapaifang-collector-desktop-target"
}

$previousRuntime = $null
$runtimeConfigPath = Join-Path $deployRoot "crow-desktop.runtime.json"
if (Test-Path -LiteralPath $runtimeConfigPath -PathType Leaf) {
    try {
        $previousRuntime = Get-Content -LiteralPath $runtimeConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw 'Existing desktop runtime configuration is invalid; deployment was not started.'
    }
}
$previousEnvironment = if ($previousRuntime) { $previousRuntime.environment } else { $null }
if (-not $ApiBase) { $ApiBase = [string]$previousEnvironment.FAPAI_COLLECTOR_API_BASE }
if (-not $ApiCaFile) { $ApiCaFile = [string]$previousEnvironment.FAPAI_API_CA_FILE }
if (-not $SettingsApiBase) { $SettingsApiBase = [string]$previousEnvironment.FAPAI_SETTINGS_API_BASE }
if (-not $SettingsCaFile) { $SettingsCaFile = [string]$previousEnvironment.FAPAI_SETTINGS_CA_FILE }
if (-not $OperatorTokenFile) { $OperatorTokenFile = [string]$previousEnvironment.FAPAI_ENGINE_OPERATOR_TOKEN_FILE }
. (Join-Path $PSScriptRoot 'collection-api-origin.ps1')
$ApiBase = ConvertTo-CollectionApiOrigin -ApiBase $ApiBase
if ($ApiCaFile -and -not (Test-Path -LiteralPath $ApiCaFile -PathType Leaf)) {
    throw 'Collection API CA file is unavailable; deployment was not started.'
}
if ($SettingsApiBase -or $SettingsCaFile -or $OperatorTokenFile) {
    $settingsUri = [uri]$SettingsApiBase
    if (-not $settingsUri.IsAbsoluteUri -or $settingsUri.Scheme -ne 'https' -or $settingsUri.UserInfo -or $settingsUri.Query -or $settingsUri.Fragment -or $settingsUri.AbsolutePath -ne '/' -or -not $SettingsCaFile -or -not $OperatorTokenFile) {
        throw 'Settings requires an HTTPS origin, application CA file and operator token file; deployment was not started.'
    }
    if (-not (Test-Path -LiteralPath $SettingsCaFile -PathType Leaf)) {
        throw 'Settings API CA file is unavailable; deployment was not started.'
    }
    if (-not (Test-Path -LiteralPath $OperatorTokenFile -PathType Leaf)) {
        throw 'Settings operator token file is unavailable; deployment was not started.'
    }
}
if (-not $DataRoot) {
    $previousCrowRoot = [string]$previousEnvironment.CROW_DATA_ROOT_HOST
    $previousLegacyRoot = [string]$previousEnvironment.FAPAI_DATA_ROOT_HOST
    if ($previousCrowRoot -and $previousLegacyRoot -and
        -not [string]::Equals([IO.Path]::GetFullPath($previousCrowRoot), [IO.Path]::GetFullPath($previousLegacyRoot), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Installed desktop has conflicting Crow/legacy data roots; select -DataRoot explicitly."
    }
    $DataRoot = if ($previousCrowRoot) { $previousCrowRoot } else { $previousLegacyRoot }
}
if (-not $DataRoot) {
    $DataRoot = Resolve-CrowProjectDataRoot -RepoRoot $repoRoot
}
if (-not $CookieSnapshotPath -and $previousEnvironment.FAPAI_COOKIE_SNAPSHOT) {
    $CookieSnapshotPath = [string]$previousEnvironment.FAPAI_COOKIE_SNAPSHOT
}
if (-not $AuthBrowserProfileDir -and $previousEnvironment.FAPAI_AUTH_BROWSER_PROFILE_DIR) {
    $AuthBrowserProfileDir = [string]$previousEnvironment.FAPAI_AUTH_BROWSER_PROFILE_DIR
}
if (-not $AuthBrowserProfileDir) {
    $AuthBrowserProfileDir = Join-Path $DataRoot "chrome-cdp-profile-pc1-human-clean"
}

$buildExecutable = Join-Path $resolvedBuildTargetRoot "release\fapaifang_collector_desktop.exe"
$destinationExecutable = Join-Path $deployRoot "fapaifang_collector_desktop.exe"
$launcherPath = Join-Path $deployRoot "start-fapaifang-collector.ps1"
$resolvedRemoteAuthKeyPath = Resolve-RemoteAuthKeyPath -ExplicitPath $RemoteAuthKeyPath
$resolvedCookieSnapshotPath = if ($CookieSnapshotPath) {
    $CookieSnapshotPath
} else {
    Join-Path $DataRoot "secrets\nodes\pc2\taobao-cookies.json"
}

if (-not $SkipBuild) {
    Invoke-CollectorDesktopBuild -CollectorRoot $collectorRoot -TargetRoot $resolvedBuildTargetRoot
}

if (-not (Test-Path -LiteralPath $buildExecutable)) {
    throw "Built desktop executable not found: $buildExecutable"
}

New-Item -ItemType Directory -Force -Path $deployRoot | Out-Null
Stop-ExistingCollectorDesktop
Backup-ExistingInstall -DestinationRoot $deployRoot

Copy-Item -LiteralPath $buildExecutable -Destination $destinationExecutable -Force

foreach ($relativePath in @(
        "scripts\open-remote-auth-browser.ps1",
        "scripts\start-pc1-manual-auth-session.ps1",
        "scripts\start-pc1-auth-bridge.ps1",
        "scripts\watch-pc1-auth-auto-resume.ps1",
        "scripts\watch-pc1-nas-auth-recovery.ps1",
        "scripts\collection-api-origin.ps1",
        "scripts\project-data-root.ps1",
        "scripts\pc1-recovery-http.ps1",
        "scripts\pc1-auth-recovery-policy.ps1",
        "scripts\register-pc1-nas-auth-recovery-task.ps1",
        "scripts\register-pc1-shared-auth-maintenance.ps1",
        "scripts\register-taobao-login-watchdog-task.ps1",
        "scripts\taobao-login-watchdog.ps1",
        "scripts\start-pc1-analysis-proxy-bridge.ps1",
        "scripts\register-pc1-analysis-proxy-bridge-task.ps1",
        "scripts\start-taobao-cdp-browser.ps1",
        "scripts\start-taobao-cdp-browser\http-and-pages.ps1",
        "scripts\start-taobao-cdp-browser\browser-processes.ps1",
        "scripts\export-taobao-cookie-snapshot.ps1",
        "scripts\complete-pc1-inplace-auth.ps1",
        "scripts\resolve-pc1-auth-python.ps1",
        "scripts\desktop-auth-challenge.ps1",
        "tools\pc1_desktop_auth.py",
        "tools\pc1_shared_auth.py",
        "tools\pc1_desktop_recovery.py",
        "tools\pc1_recovery_request.py",
        "tools\background_task_launcher.py",
        "tools\desktop_runtime_config.py",
        "tools\desktop_environment.py",
        "tools\desktop_settings_client.py",
        "src\auth_recovery_codes.py",
        "src\project_data_paths.py",
        "src\project_environment.py",
        "src\auth_snapshot_contract.py",
        "src\cdp_cookie_transport.py",
        "src\cookie_snapshot_metadata.py",
        "src\cookie_snapshot_storage.py",
        "src\collection_api_credentials.py",
        "src\collection_settings_schema.py",
        "src\collection\adapters\taobao_auth_target.py",
        "src\collection\adapters\taobao_health.py",
        "src\collection\adapters\taobao_list_probe.py",
        "src\collection_engine_restart.py",
        "src\collection_operator_actions.py",
        "src\llm_analysis_policy.py",
        "tools\manual_auth_snapshot.py",
        "tools\browserless_seed_probe.py",
        "tools\browserless_seed_probe_context.py",
        "tools\browserless_seed_probe_core.py",
        "tools\browserless_seed_probe_transport.py",
        "tools\browserless_seed_probe_navigation.py",
        "tools\browserless_seed_probe_cookies.py",
        "tools\browserless_seed_probe_cli.py",
        "tools\taobao_login_health.py",
        "tools\taobao_health_context.py",
        "tools\taobao_health_classification.py",
        "tools\taobao_health_cdp_transport.py",
        "tools\taobao_health_captcha.py",
        "tools\taobao_health_cdp_session.py",
        "tools\taobao_health_probe.py",
        "tools\taobao_health_cli.py",
        "tools\taobao_inplace_auth_handoff.py",
        "tools\internal_api_http.py"
    )) {
    Copy-BundleFile -SourceRoot $repoRoot -DestinationRoot $deployRoot -RelativePath $relativePath
}

& (Join-Path $PSScriptRoot 'write-collector-desktop-runtime-config.ps1') `
    -InstallRoot $deployRoot -DataRoot $DataRoot -ApiBase $ApiBase -ApiCaFile $ApiCaFile `
    -CookieSnapshotPath $resolvedCookieSnapshotPath -AuthLocalCdpPort $AuthLocalCdpPort `
    -AuthBrowserProfileDir $AuthBrowserProfileDir -AuthBrowserPath $AuthBrowserPath `
    -SettingsApiBase $SettingsApiBase -SettingsCaFile $SettingsCaFile -OperatorTokenFile $OperatorTokenFile

Write-LauncherScript `
    -LauncherPath $launcherPath `
    -ExecutablePath $destinationExecutable `
    -ApiBaseUrl $ApiBase `
    -RemoteHost $RemoteAuthHost `
    -RemoteUserName $RemoteAuthUser `
    -RemotePasswordValue $RemoteAuthPassword `
    -RemoteKeyPath $resolvedRemoteAuthKeyPath `
    -DataRootValue $DataRoot `
    -CookieSnapshotValue $resolvedCookieSnapshotPath `
    -AuthBrowserModeValue $AuthBrowserMode `
    -AuthLocalCdpPortValue $AuthLocalCdpPort `
    -AuthRemoteCdpPortValue $AuthRemoteCdpPort `
    -AuthBrowserProfileDirValue $AuthBrowserProfileDir `
    -AuthBrowserPathValue $AuthBrowserPath

if (-not $SkipShortcut) {
    $shortcut = & (Join-Path $PSScriptRoot 'update-collector-desktop-shortcut.ps1') `
        -InstallRoot $deployRoot -DesktopDirectory $DesktopDirectory `
        -ExpectedSha256 (Get-FileHash -LiteralPath $buildExecutable -Algorithm SHA256).Hash
}

if (-not $SkipLaunch) {
    $powershellExecutable = (Get-Command powershell -ErrorAction Stop).Source
    Start-Process `
        -FilePath $powershellExecutable `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcherPath) `
        -WorkingDirectory $deployRoot `
        -WindowStyle Hidden
}

Write-Output "Collector desktop deployed to: $deployRoot"
Write-Output "Desktop executable: $destinationExecutable"
Write-Output "Launcher script: $launcherPath"
if (-not $SkipShortcut) {
    Write-Output "Desktop shortcut: $($shortcut.path)"
}
