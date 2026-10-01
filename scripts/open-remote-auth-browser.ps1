param(
    [int]$Port = 9223,
    [string]$StartUrl = "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    [string]$RemoteHost = "",
    [string]$RemoteUser = "",
    [string]$RemotePassword = "",
    [string]$RemoteKeyPath = "",
    [string]$RemoteProfileDir = "",
    [string]$RemoteBrowserScript = "",
    [ValidateSet("remote", "local-bridge")][string]$AuthMode = ""
)
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot 'project-environment.ps1')




function Get-LocalAuthBrowserScript {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "start-taobao-cdp-browser.ps1")).ProviderPath
}

function Start-LocalAuthAutoResumeWatcher {
    $watcherScript = Join-Path $PSScriptRoot "watch-pc1-auth-auto-resume.ps1"
    if (-not (Test-Path -LiteralPath $watcherScript)) {
        Write-Host "PC1 auth auto-resume watcher script is missing; skip background watcher."
        return
    }
    $existing = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -eq "powershell.exe" -and
                ([string]$_.CommandLine).IndexOf($watcherScript, [StringComparison]::OrdinalIgnoreCase) -ge 0
            }
    )
    if ($existing.Count -gt 0) {
        Write-Host "PC1 auth auto-resume watcher is already running."
        return
    }
    $watcherArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $watcherScript,
        "-Port",
        "9225"
    )
    Start-Process -FilePath "powershell.exe" -ArgumentList $watcherArgs -WindowStyle Hidden | Out-Null
}

function Start-LocalAuthBrowserFallback {
    $localScript = Get-LocalAuthBrowserScript
    Write-Host "Remote auth browser helper unavailable; falling back to local auth browser helper."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $localScript -Port $Port -StartUrl $StartUrl
}

$resolvedAuthMode = if ($AuthMode) {
    $AuthMode
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_AUTH_BROWSER_MODE')) {
    (Get-CrowEnvironmentValue -Name 'CROW_AUTH_BROWSER_MODE')
} else {
    "remote"
}

if ($resolvedAuthMode -eq "local-bridge") {
    $manualAuthScript = if ((Get-CrowEnvironmentValue -Name 'CROW_AUTH_BRIDGE_SCRIPT' -PathValue)) {
        (Get-CrowEnvironmentValue -Name 'CROW_AUTH_BRIDGE_SCRIPT' -PathValue)
    } else {
        Join-Path $PSScriptRoot "start-pc1-auth-bridge.ps1"
    }
    if (-not (Test-Path -LiteralPath $manualAuthScript)) {
        throw "Local PC1 manual-auth script does not exist: $manualAuthScript"
    }
    $manualAuthArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $manualAuthScript,
        "-LocalCdpPort",
        "9225",
        "-RemoteCdpPort",
        "9225",
        "-StartUrl",
        $StartUrl
    )
    & powershell.exe @manualAuthArgs
    if ($LASTEXITCODE -eq 0) {
        Start-LocalAuthAutoResumeWatcher
    }
    exit $LASTEXITCODE
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

$resolvedRemotePassword = if ($RemotePassword) {
    $RemotePassword
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_PASSWORD')) {
    (Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_PASSWORD')
} else {
    ""
}

$resolvedRemoteKeyPath = if ($RemoteKeyPath) {
    $RemoteKeyPath
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_KEY_PATH' -PathValue)) {
    (Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_KEY_PATH' -PathValue)
} else {
    ""
}

$resolvedRemoteProfileDir = if ($RemoteProfileDir) {
    $RemoteProfileDir
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_PROFILE_DIR')) {
    (Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_PROFILE_DIR')
} else {
    "C:\Users\Public\nas_home\AI\FPFData\edge-cdp-profile-pc2"
}

$resolvedRemoteBrowserScript = if ($RemoteBrowserScript) {
    $RemoteBrowserScript
} elseif ((Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_REMOTE_SCRIPT')) {
    (Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_REMOTE_SCRIPT')
} else {
    "C:\fapaifang-worker\ops\trigger-open-auth-task.ps1"
}

if (-not $resolvedRemotePassword -and -not $resolvedRemoteKeyPath) {
    Start-LocalAuthBrowserFallback
    exit 0
}

try {
    $pythonCommand = Get-Command python -ErrorAction Stop
} catch {
    Write-Host "python command unavailable for remote auth helper: $($_.Exception.Message)"
    Start-LocalAuthBrowserFallback
    exit 0
}

$escapedRemoteBrowserScript = $resolvedRemoteBrowserScript.Replace("'", "''")
$escapedRemoteProfileDir = $resolvedRemoteProfileDir.Replace("'", "''")
$escapedStartUrl = $StartUrl.Replace("'", "''")
$remoteCommand = "powershell -NoProfile -ExecutionPolicy Bypass -Command ""& '$escapedRemoteBrowserScript' -Port $Port -ProfileDir '$escapedRemoteProfileDir' -StartUrl '$escapedStartUrl'"""

Set-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_HOST_ACTIVE' -Value ($resolvedRemoteHost)
Set-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_USER_ACTIVE' -Value ($resolvedRemoteUser)
Set-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_PASSWORD_ACTIVE' -Value ($resolvedRemotePassword)
Set-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_KEY_PATH_ACTIVE' -Value ($resolvedRemoteKeyPath)
Set-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_COMMAND' -Value ($remoteCommand)

$pythonCode = @'
import os
import sys

import paramiko

host = os.environ["CROW_REMOTE_AUTH_HOST_ACTIVE"]
user = os.environ["CROW_REMOTE_AUTH_USER_ACTIVE"]
password = os.environ.get("CROW_REMOTE_AUTH_PASSWORD_ACTIVE") or None
key_path = os.environ.get("CROW_REMOTE_AUTH_KEY_PATH_ACTIVE") or None
command = os.environ["CROW_REMOTE_AUTH_COMMAND"]

connect_kwargs = {
    "hostname": host,
    "username": user,
    "password": password,
    "timeout": 20,
    "allow_agent": True,
    "look_for_keys": True,
}
if key_path:
    connect_kwargs["key_filename"] = key_path

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(**connect_kwargs)
stdin, stdout, stderr = client.exec_command(command)
_ = stdout.read()
error_output = stderr.read().decode("utf-8", "ignore").strip()
client.close()

if error_output:
    print(error_output, file=sys.stderr)
    raise SystemExit(1)
'@

$pythonScript = New-TemporaryFile
$pythonScriptPath = "$($pythonScript.FullName).py"
Move-Item -LiteralPath $pythonScript.FullName -Destination $pythonScriptPath -Force
Set-Content -LiteralPath $pythonScriptPath -Value $pythonCode -Encoding UTF8

try {
    & $pythonCommand.Source $pythonScriptPath
}
finally {
    Remove-Item -LiteralPath $pythonScriptPath -Force -ErrorAction SilentlyContinue
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "Remote auth browser helper failed; falling back to local auth browser helper."
    Start-LocalAuthBrowserFallback
    exit 0
}

Write-Host "Triggered remote auth browser on $resolvedRemoteHost."
