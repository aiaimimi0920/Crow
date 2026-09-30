param(
    [int]$LocalCdpPort = 9225,
    [int]$RemoteCdpPort = 9225,
    [int]$ReportCdpPort = 9224,
    [string]$RemoteHost = "",
    [string]$RemoteUser = "",
    [string]$RemoteKeyPath = "",
    [string]$ProfileDir = "",
    [string]$BrowserPath = "",
    [string]$StartUrl = "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    [string]$DataRoot = "",
    [int]$TunnelStartupTimeoutSeconds = 30,
    [switch]$SkipBrowserStart
)
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot 'project-environment.ps1')



. (Join-Path $PSScriptRoot "project-data-root.ps1")

function Get-CdpEndpointProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [switch]$RequireRemoteWebSocket
    )

    $probe = [ordered]@{
        endpoint = $Endpoint
        healthy = $false
        error = ""
        websocket_url = ""
        raw_body = ""
    }

    $response = $null
    try {
        $request = [System.Net.HttpWebRequest]::Create("$($Endpoint.TrimEnd('/'))/json/version")
        $request.Proxy = $null
        $request.Timeout = 3000
        $request.ReadWriteTimeout = 3000
        $request.KeepAlive = $false
        $response = [System.Net.HttpWebResponse]$request.GetResponse()
        $stream = $response.GetResponseStream()
        if ($null -ne $stream) {
            $reader = New-Object System.IO.StreamReader($stream)
            try {
                $probe.raw_body = $reader.ReadToEnd()
            }
            finally {
                $reader.Dispose()
            }
        }
    }
    catch {
        $probe.error = $_.Exception.Message
        return [pscustomobject]$probe
    }
    finally {
        if ($null -ne $response) {
            $response.Close()
        }
    }

    if ($response.StatusCode -ne 200) {
        $probe.error = "unexpected_status_$($response.StatusCode)"
        return [pscustomobject]$probe
    }

    try {
        $payload = [string]($probe.raw_body) | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        $probe.error = "invalid_json_version_payload"
        return [pscustomobject]$probe
    }

    $websocketUrl = [string]($payload.webSocketDebuggerUrl)
    if (-not $websocketUrl) {
        $probe.error = "missing_websocket_debugger_url"
        return [pscustomobject]$probe
    }
    $probe.websocket_url = $websocketUrl

    if ($RequireRemoteWebSocket) {
        try {
            $endpointUri = [System.Uri]$Endpoint
            $websocketUri = [System.Uri]$websocketUrl
        }
        catch {
            $probe.error = "invalid_websocket_debugger_url"
            return [pscustomobject]$probe
        }

        if ($websocketUri.Host -in @("127.0.0.1", "localhost", "0.0.0.0")) {
            $probe.error = "loopback_websocket_url"
            return [pscustomobject]$probe
        }
        if ($websocketUri.Host -ne $endpointUri.Host -or $websocketUri.Port -ne $endpointUri.Port) {
            $probe.error = "remote_websocket_mismatch"
            return [pscustomobject]$probe
        }
    }

    $probe.healthy = $true
    return [pscustomobject]$probe
}

function Resolve-DataRoot {
    return Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot
}

function Resolve-SshExecutable {
    $command = Get-Command ssh.exe -ErrorAction Stop
    return $command.Source
}

function Resolve-KeyPath {
    if ($RemoteKeyPath) {
        return $RemoteKeyPath
    }
    if ((Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_KEY_PATH' -PathValue)) {
        return (Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_KEY_PATH' -PathValue)
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

function Get-TunnelProcesses {
    param([Parameter(Mandatory = $true)][string]$Marker)

    return @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -eq "ssh.exe" -and
                ([string]$_.CommandLine).IndexOf($Marker, [StringComparison]::OrdinalIgnoreCase) -ge 0
            }
    )
}

function Stop-TunnelProcesses {
    param([Parameter(Mandatory = $true)][string]$Marker)

    foreach ($process in (Get-TunnelProcesses -Marker $Marker)) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

$resolvedRemoteHost = if ($RemoteHost) {
    $RemoteHost
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_HOST')) {
    (Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_HOST')
} else {
    "192.168.15.104"
}
$resolvedRemoteUser = if ($RemoteUser) {
    $RemoteUser
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_USER')) {
    (Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_USER')
} else {
    "Admin"
}
$resolvedKeyPath = Resolve-KeyPath
$resolvedProfileDir = if ($ProfileDir) {
    $ProfileDir
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_AUTH_BROWSER_PROFILE_DIR' -PathValue)) {
    (Get-CrowEnvironmentValue -Name 'CROW_AUTH_BROWSER_PROFILE_DIR' -PathValue)
} else {
    Join-Path (Resolve-DataRoot) "chrome-cdp-profile-pc1-human-clean"
}
$resolvedBrowserPath = if ($BrowserPath) {
    $BrowserPath
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_AUTH_BROWSER_PATH' -PathValue)) {
    (Get-CrowEnvironmentValue -Name 'CROW_AUTH_BROWSER_PATH' -PathValue)
} else {
    "C:\Program Files\Google\Chrome\Application\chrome.exe"
}
$resolvedDataRoot = Resolve-DataRoot
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$browserScript = Join-Path $repoRoot "scripts\start-taobao-cdp-browser.ps1"
$ssh = Resolve-SshExecutable
$target = "$resolvedRemoteUser@$resolvedRemoteHost"
$forwardSpec = "127.0.0.1:{0}:127.0.0.1:{1}" -f $RemoteCdpPort, $LocalCdpPort
$marker = "-R $forwardSpec"
$stateDir = Join-Path $resolvedDataRoot "secrets"
$statePath = Join-Path $stateDir "pc1-auth-bridge-state.json"
$logPath = Join-Path $stateDir "pc1-auth-bridge.log"
$errorLogPath = Join-Path $stateDir "pc1-auth-bridge.err.log"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

if (-not (Test-Path -LiteralPath $browserScript)) {
    throw "Missing human auth browser script: $browserScript"
}
if (-not (Test-Path -LiteralPath $resolvedBrowserPath)) {
    throw "Configured human auth browser does not exist: $resolvedBrowserPath"
}
if ($SkipBrowserStart) {
    $localProbe = Get-CdpEndpointProbe -Endpoint "http://127.0.0.1:$LocalCdpPort"
    if (-not $localProbe.healthy) {
        throw "PC1 human auth CDP is unavailable on port $LocalCdpPort and browser start was skipped (error=$($localProbe.error))."
    }
}
else {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $browserScript `
        -Port $LocalCdpPort `
        -ProfileDir $resolvedProfileDir `
        -BrowserPath $resolvedBrowserPath `
        -DebuggingAddress "127.0.0.1" `
        -StartUrl $StartUrl `
        -UseSystemProxy `
        -HumanAuthMode `
        -CdpStartupTimeoutSeconds $TunnelStartupTimeoutSeconds
}
$localProbe = Get-CdpEndpointProbe -Endpoint "http://127.0.0.1:$LocalCdpPort"
if (-not $localProbe.healthy) {
    throw "PC1 human auth CDP did not become healthy on port $LocalCdpPort (error=$($localProbe.error))."
}

$existing = @(Get-TunnelProcesses -Marker $marker)
if ($existing.Count -eq 0) {
    $tunnelArguments = @(
        "-N",
        "-T",
        "-o", "BatchMode=yes",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        "-o", "ConnectTimeout=10",
        "-R", $forwardSpec
    )
    if ($resolvedKeyPath) {
        $tunnelArguments += @("-i", $resolvedKeyPath)
    }
    $tunnelArguments += $target
    $tunnel = Start-Process -FilePath $ssh -ArgumentList $tunnelArguments -WindowStyle Hidden -RedirectStandardOutput $logPath -RedirectStandardError $errorLogPath -PassThru
    Start-Sleep -Seconds 2
    if ($tunnel.HasExited) {
        throw "PC1 to PC2 CDP reverse tunnel exited with code $($tunnel.ExitCode). See $logPath."
    }
}

$deadline = (Get-Date).AddSeconds([Math]::Max($TunnelStartupTimeoutSeconds, 1))
$remoteReady = $false
$reportEndpoint = "http://$resolvedRemoteHost`:$ReportCdpPort"
$lastTunnelCount = 0
$lastReportProbe = [pscustomobject]@{
    endpoint = $reportEndpoint
    healthy = $false
    error = "not_probed"
    websocket_url = ""
}
while ((Get-Date) -lt $deadline) {
    $tunnelProcesses = @(Get-TunnelProcesses -Marker $marker)
    $lastTunnelCount = $tunnelProcesses.Count
    $lastReportProbe = Get-CdpEndpointProbe -Endpoint $reportEndpoint -RequireRemoteWebSocket
    if ($lastTunnelCount -gt 0 -and $lastReportProbe.healthy) {
        $remoteReady = $true
        break
    }
    Start-Sleep -Seconds 2
}
if (-not $remoteReady) {
    Stop-TunnelProcesses -Marker $marker
    throw (
        "PC2 CDP reverse tunnel is not healthy on 127.0.0.1:$RemoteCdpPort " +
        "(tunnel_processes=$lastTunnelCount, report_endpoint_healthy=$($lastReportProbe.healthy), " +
        "report_endpoint_error=$($lastReportProbe.error), report_websocket_url=$($lastReportProbe.websocket_url))."
    )
}

[pscustomobject]@{
    mode = "pc1_human_auth_reverse_tunnel"
    local_cdp_endpoint = "http://127.0.0.1:$LocalCdpPort"
    remote_cdp_endpoint = "http://127.0.0.1:$RemoteCdpPort"
    report_cdp_endpoint = $reportEndpoint
    report_cdp_websocket_url = $lastReportProbe.websocket_url
    remote_host = $resolvedRemoteHost
    remote_user = $resolvedRemoteUser
    profile_dir = $resolvedProfileDir
    state_path = $statePath
    checked_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding UTF8

Write-Output "PC1 human auth browser is ready on http://127.0.0.1:$LocalCdpPort."
Write-Output "PC2 workers can use the private reverse tunnel on http://127.0.0.1:$RemoteCdpPort."
Write-Output "Complete Taobao authentication in the visible PC1 browser and keep it open."
