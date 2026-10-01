param(
    [int]$Port = 9223,
    [string]$DataRoot = "",
    [string]$ProfileDir = "",
    [string]$BrowserPath = "",
    [string]$DebuggingAddress = "0.0.0.0",
    [string]$StartUrl = "https://sf.taobao.com/",
    [switch]$UseSystemProxy,
    [switch]$DisableExtensions,
    [switch]$HumanAuthMode,
    [switch]$StartMinimized,
    [switch]$EnsureOnly,
    [int]$CdpStartupTimeoutSeconds = 30,
    [int]$StartupLockTimeoutSeconds = 180,
    [switch]$IsolatedProfile,
    [switch]$ForceNew,
    [switch]$TerminateAllBrowserProcesses
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")

$script:TaobaoCdpBrowserScriptRoot = $PSScriptRoot
$moduleRoot = Join-Path $PSScriptRoot "start-taobao-cdp-browser"
. (Join-Path $moduleRoot "http-and-pages.ps1")
. (Join-Path $moduleRoot "browser-processes.ps1")

$startupMutex = [System.Threading.Mutex]::new(
    $false,
    "FapaiFangTaobaoCdp-$Port"
)
$startupLockAcquired = $false
try {
    try {
        $startupLockAcquired = $startupMutex.WaitOne(
            [TimeSpan]::FromSeconds([Math]::Max($StartupLockTimeoutSeconds, 1))
        )
    }
    catch [System.Threading.AbandonedMutexException] {
        $startupLockAcquired = $true
    }
    if (-not $startupLockAcquired) {
        throw "Timed out waiting for the CDP startup lock on port $Port."
    }

$dataRoot = Resolve-FapaiDataRoot
if (-not $ProfileDir) {
    if ($IsolatedProfile) {
        $ProfileDir = Join-Path $dataRoot "edge-cdp-profile-isolated"
    }
    else {
        $ProfileDir = Join-Path $dataRoot "edge-cdp-profile"
    }
}

$hostEndpoint = "http://127.0.0.1:$Port"
$dockerEndpoint = "http://192.168.65.254:$Port"
$resolvedDebuggingAddress = if ($HumanAuthMode) { "127.0.0.1" } else { $DebuggingAddress }

if ($ForceNew) {
    if (-not (Stop-ExistingCdpBrowser `
        -Port $Port `
        -ProfileDir $ProfileDir `
        -Endpoint $hostEndpoint `
        -AllBrowserProcesses:$TerminateAllBrowserProcesses
    )) {
        throw "Existing CDP browser processes did not exit cleanly for port $Port / profile $ProfileDir."
    }
}
elseif (Test-CdpEndpoint -Endpoint $hostEndpoint) {
    Write-Output "Existing CDP endpoint is available: $hostEndpoint"
    if (-not $EnsureOnly) {
        if (Test-BrowserProcessOpenPreferred -Url $StartUrl) {
            Write-Host "Skipping CDP /json/new for challenge-sized auth URL when no matching tab exists."
        }
        try {
            # Always inspect/reuse an existing auth or challenge tab first.
            # Only fall back to a browser process when CDP cannot open the URL;
            # this prevents long challenge URLs from bypassing deduplication.
            Open-CdpBrowserPage -Endpoint $hostEndpoint -Url $StartUrl
        }
        catch {
            Write-Host "CDP /json/new open failed; falling back to browser process URL open: $($_.Exception.Message)"
            $browser = Find-BrowserExecutable -PreferredPath $BrowserPath
            Open-BrowserProcessPage -Browser $browser -ProfileDir $ProfileDir -Port $Port -DebuggingAddress $resolvedDebuggingAddress -Url $StartUrl
        }
        Show-CdpBrowserWindow -Port $Port -ProfileDir $ProfileDir -AllBrowserProcesses:$TerminateAllBrowserProcesses
    }
    else {
        Write-Output "CDP endpoint is already healthy; ensure-only mode will not open a page."
    }
    Write-Output "Docker containers should use: $dockerEndpoint"
    Write-Output "Log in to Taobao in the opened browser window if it is not already authenticated."
    return
}
else {
    $staleProcesses = @(Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir)
    if ($staleProcesses.Count -gt 0) {
        Write-Host "Existing CDP browser process exists but endpoint is unavailable; restarting the dedicated auth browser."
        if (-not (Stop-ExistingCdpBrowser -Port $Port -ProfileDir $ProfileDir -Endpoint $hostEndpoint)) {
            throw "Stale CDP browser processes did not exit cleanly for port $Port / profile $ProfileDir."
        }
    }
}

New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

$browser = Find-BrowserExecutable -PreferredPath $BrowserPath
$arguments = @(
    "--remote-debugging-port=$Port",
    "--remote-debugging-address=$resolvedDebuggingAddress",
    "--remote-allow-origins=*",
    "--user-data-dir=$ProfileDir",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-session-crashed-bubble",
    $StartUrl
)

if (-not $HumanAuthMode) {
    $arguments += @(
        "--disable-blink-features=AutomationControlled",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-client-side-phishing-detection",
        "--disable-default-apps",
        "--disable-restore-session-state"
    )
}

if (-not $UseSystemProxy) {
    $arguments += "--no-proxy-server"
}
if ($DisableExtensions) {
    $arguments += "--disable-extensions"
}
if ($StartMinimized) {
    $arguments += "--start-minimized"
}

Start-Process `
    -FilePath $browser `
    -ArgumentList $arguments `
    -WorkingDirectory (Split-Path -Parent $browser) `
    -WindowStyle Normal

if (-not (Wait-CdpEndpoint -Endpoint $hostEndpoint -TimeoutSeconds $CdpStartupTimeoutSeconds)) {
    throw "Started browser but CDP endpoint did not become available within $CdpStartupTimeoutSeconds seconds: $hostEndpoint/json/version"
}

Show-CdpBrowserWindow -Port $Port -ProfileDir $ProfileDir -AllBrowserProcesses:$TerminateAllBrowserProcesses
Write-Output "Started browser: $browser"
Write-Output "Profile directory: $ProfileDir"
Write-Output "Host CDP endpoint: $hostEndpoint"
Write-Output "Docker CDP endpoint: $dockerEndpoint"
Write-Output "Human auth mode: $($HumanAuthMode.IsPresent)"
Write-Output "Log in to Taobao in the opened browser window, then keep the window open for collectors."
}
finally {
    if ($startupLockAcquired) {
        try {
            $startupMutex.ReleaseMutex()
        }
        catch {
        }
    }
    $startupMutex.Dispose()
}
