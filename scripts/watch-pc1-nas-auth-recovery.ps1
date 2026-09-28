param(
    [string]$ApiBase = "",
    [string]$DataRoot = "",
    [string]$OutputPath = "",
    [string]$TokenPath = "",
    [string]$ApiCaFile = "",
    [int]$Port = 9225,
    [string]$Python = "",
    [string]$ProfileDir = "",
    [string]$BrowserPath = "",
    [string]$StartUrl = "https://sf.taobao.com/list/50025969__2.htm",
    [int]$LoginWindowSeconds = 300,
    [switch]$UseSystemProxy
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "collection-api-origin.ps1")
. (Join-Path $PSScriptRoot "pc1-recovery-http.ps1")

function Resolve-ApiBase {
    $value = if ($ApiBase) {
        $ApiBase
    }
    elseif ($env:FAPAI_COLLECTOR_API_BASE) {
        $env:FAPAI_COLLECTOR_API_BASE
    }
    elseif ($env:FAPAI_API_BASE_URL) {
        $env:FAPAI_API_BASE_URL
    }
    else {
        ""
    }
    return (ConvertTo-CollectionApiOrigin $value) + "/api"
}

$apiBaseResolved = Resolve-ApiBase
if (-not $ApiCaFile) { $ApiCaFile = $env:FAPAI_API_CA_FILE }
if ($ApiCaFile -and -not (Test-Path -LiteralPath $ApiCaFile -PathType Leaf)) {
    throw "Collection API CA file is unavailable."
}

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
    $temporaryPath = "$Path.$PID.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        [System.IO.File]::WriteAllText($temporaryPath, $Content, $utf8NoBom)
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

function Read-State {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Write-State {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$State
    )
    $updatedAt = (Get-Date).ToUniversalTime().ToString("o")
    if ($State -is [System.Collections.IDictionary]) {
        $State["updated_at"] = $updatedAt
    }
    else {
        $State | Add-Member -NotePropertyName updated_at -NotePropertyValue $updatedAt -Force
    }
    Write-Utf8NoBomFile -Path $Path -Content ($State | ConvertTo-Json -Depth 6)
}

function Invoke-RecoveryRequest {
    param(
        [string]$Action = "status",
        $Body = $null
    )
    return Invoke-Pc1RecoveryApi -Python $Python -ApiBase $apiBaseResolved `
        -DataRoot $DataRoot -TokenPath $TokenPath -ApiCaFile $ApiCaFile `
        -Action $Action -Body $Body
}

function Get-CdpTabs {
    param([Parameter(Mandatory = $true)][string]$Endpoint)
    $uri = "$($Endpoint.TrimEnd('/'))/json/list"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($null -ne $curl) {
        try {
            $payload = & $curl.Source `
                --silent `
                --show-error `
                --fail `
                --connect-timeout 2 `
                --max-time 3 `
                --noproxy "127.0.0.1,localhost" `
                $uri 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $payload) {
                return @()
            }
            $parsed = [string]::Join("`n", @($payload)) | ConvertFrom-Json
            return $parsed
        }
        catch {
            return @()
        }
    }

    try {
        $request = [System.Net.HttpWebRequest]::Create($uri)
        $request.Proxy = $null
        $request.KeepAlive = $false
        $request.Timeout = 3000
        $request.ReadWriteTimeout = 3000
        $response = [System.Net.HttpWebResponse]$request.GetResponse()
        try {
            $stream = $response.GetResponseStream()
            $stream.ReadTimeout = 3000
            $reader = New-Object System.IO.StreamReader($stream)
            try {
                $parsed = $reader.ReadToEnd() | ConvertFrom-Json
                return $parsed
            }
            finally {
                $reader.Dispose()
            }
        }
        finally {
            $response.Close()
        }
    }
    catch {
        return @()
    }
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$pythonResolver = Join-Path $PSScriptRoot "resolve-pc1-auth-python.ps1"
if (-not (Test-Path -LiteralPath $pythonResolver -PathType Leaf)) {
    throw "Missing PC1 auth Python resolver."
}
. $pythonResolver
$Python = Resolve-Pc1AuthPython -Requested $Python
. (Join-Path $PSScriptRoot "pc1-auth-recovery-policy.ps1")
. (Join-Path $PSScriptRoot "start-taobao-cdp-browser\http-and-pages.ps1")
. (Join-Path $PSScriptRoot "start-taobao-cdp-browser\browser-processes.ps1")
$startBrowserScript = Join-Path $repoRoot "scripts\start-taobao-cdp-browser.ps1"
$completeAuthScript = Join-Path $repoRoot "scripts\complete-pc1-inplace-auth.ps1"
foreach ($required in @($startBrowserScript, $completeAuthScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing PC1 auth recovery helper: $required"
    }
}

if (-not $DataRoot) {
    $DataRoot = if ($env:FAPAI_DATA_ROOT_HOST) {
        $env:FAPAI_DATA_ROOT_HOST
    } else {
        Join-Path (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath "FPFData"
    }
}
if (-not $OutputPath) {
    $OutputPath = if ($env:FAPAI_COOKIE_SNAPSHOT) { $env:FAPAI_COOKIE_SNAPSHOT } else { Join-Path $DataRoot "secrets\nodes\pc2\taobao-cookies.json" }
}
if (-not $TokenPath) {
    $TokenPath = if ($env:FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE) {
        $env:FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE
    } else {
        Join-Path $DataRoot "secrets\nas-auth-recovery.token"
    }
}
if (-not $ProfileDir) {
    $ProfileDir = if ($env:FAPAI_AUTH_BROWSER_PROFILE_DIR) { $env:FAPAI_AUTH_BROWSER_PROFILE_DIR } else { Join-Path $DataRoot "chrome-cdp-profile-pc1-human-clean" }
}
if (-not $BrowserPath) {
    $BrowserPath = if ($env:FAPAI_AUTH_BROWSER_PATH) { $env:FAPAI_AUTH_BROWSER_PATH } else { "C:\Program Files\Google\Chrome\Application\chrome.exe" }
}

$statePath = Join-Path $DataRoot "runtime\pc1-nas-auth-recovery-state.json"
$state = Read-State -Path $statePath
$response = Invoke-RecoveryRequest
$active = $response.auth_recovery.active
if ($null -eq $active) {
    exit 0
}
if ($active.manual_request_id) {
    # The desktop owns this explicit handoff; do not probe or publish concurrently.
    exit 0
}

$recoveryId = [string]$active.recovery_id
$status = [string]$active.status
if (-not $recoveryId -or $status -notin @("requested", "pc1_claimed")) {
    exit 0
}
if ($status -eq "requested") {
    $claim = Invoke-RecoveryRequest -Action claim `
        -Body @{ recovery_id = $recoveryId; role = "pc1"; node_id = "pc1" }
    if (-not $claim.ok) {
        exit 1
    }
}

$now = [DateTimeOffset]::UtcNow
$sameRecovery = $null -ne $state -and [string]$state.recovery_id -eq $recoveryId
$targetLookupFailed = $false
$recoveryUrl = if ($sameRecovery -and $state.target_url -and -not $state.target_lookup_failed) {
    [string]$state.target_url
} else {
    try {
        $apiStatus = Invoke-RecoveryRequest -Action public_status
        Get-Pc1RecoveryTargetUrl -SolverStatus $apiStatus.captcha_solver -FallbackUrl $StartUrl
    }
    catch {
        $targetLookupFailed = $true
        Write-Warning "NAS target lookup is unavailable; showing the auth entry point and retrying later."
        $StartUrl
    }
}
$openedAt = if ($sameRecovery -and $state.auth_window_opened_at) {
    try { [DateTimeOffset]::Parse([string]$state.auth_window_opened_at) } catch { $null }
} else {
    $null
}
$withinWindow = $null -ne $openedAt -and ($now - $openedAt).TotalSeconds -lt [Math]::Max($LoginWindowSeconds, 1)
$cdpEndpoint = "http://127.0.0.1:$Port"
$tabs = @(Get-CdpTabs -Endpoint $cdpEndpoint)
$preferredId = if ($sameRecovery) { [string]$state.target_id } else { "" }
$authTab = Get-Pc1RecoveryTab -Tabs $tabs -PreferredId $preferredId -TargetUrl $recoveryUrl

if ($null -eq $authTab -and -not $withinWindow) {
    $browserArgs = @(
        "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
        "-File", $startBrowserScript,
        "-Port", $Port,
        "-DataRoot", $DataRoot,
        "-ProfileDir", $ProfileDir,
        "-BrowserPath", $BrowserPath,
        "-DebuggingAddress", "127.0.0.1",
        "-StartUrl", $recoveryUrl,
        "-HumanAuthMode"
    )
    if ($UseSystemProxy) {
        $browserArgs += "-UseSystemProxy"
    }
    & powershell.exe @browserArgs | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "PC1 authentication browser failed to start."
    }
    $openedAt = [DateTimeOffset]::UtcNow
    $authTab = Wait-Pc1RecoveryTab -Endpoint $cdpEndpoint -TargetUrl $recoveryUrl
}
elseif ($null -eq $openedAt) {
    $openedAt = $now
}

$newState = [ordered]@{
    mode = "pc1_nas_auth_recovery"
    recovery_id = $recoveryId
    status = "waiting_for_reusable_auth"
    auth_window_opened_at = $openedAt.ToString("o")
    login_window_seconds = [Math]::Max($LoginWindowSeconds, 1)
    cdp_endpoint = $cdpEndpoint
    output_path = $OutputPath
    target_url = $recoveryUrl
    target_lookup_failed = $targetLookupFailed
    target_id = [string]$authTab.id
    prompted_at = if ($sameRecovery) { [string]$state.prompted_at } else { "" }
    seed_target_url = if ($sameRecovery) { [string]$state.seed_target_url } else { "" }
    seed_target_id = if ($sameRecovery) { [string]$state.seed_target_id } else { "" }
    seed_prompted_at = if ($sameRecovery) { [string]$state.seed_prompted_at } else { "" }
}
if ($null -ne $authTab -and (Test-Pc1RecoveryPromptDue -SameRecovery $sameRecovery `
        -PromptedAt $newState.prompted_at)) {
    # Persist the attempt before presentation; desktop failures must not cause repeat focus.
    $newState["prompted_at"] = [DateTimeOffset]::UtcNow.ToString("o")
    Write-State -Path $statePath -State $newState
    $newState["presentation"] = Show-Pc1RecoveryPrompt -Endpoint $cdpEndpoint -TargetId $authTab.id -Port $Port -ProfileDir $ProfileDir
}
Write-State -Path $statePath -State $newState
if ($null -eq $authTab) {
    Write-Output "PC1 recovery is waiting for the dedicated authentication tab; no snapshot was published."
    exit 0
}

$probeOutput = @(& powershell.exe `
    -NoProfile `
    -WindowStyle Hidden `
    -ExecutionPolicy Bypass `
    -File $completeAuthScript `
    -Port $Port `
    -DataRoot $DataRoot `
    -OutputPath $OutputPath `
    -Python $Python `
    -TargetId $authTab.id `
    -NoThrowOnPending)
$probeExit = $LASTEXITCODE
$newState["last_probe_at"] = [DateTimeOffset]::UtcNow.ToString("o")
$newState["last_probe_exit_code"] = $probeExit
Write-State -Path $statePath -State $newState
if ($probeExit -ne 0) {
    foreach ($line in $probeOutput) {
        try { $probeResult = [string]$line | ConvertFrom-Json } catch { continue }
        if ($probeResult.blocking_scope -eq 'seed') {
            try {
                $apiStatus = Invoke-RecoveryRequest -Action public_status
                Show-Pc1RecoverySeedPrompt -State $newState -StatePath $statePath -Endpoint $cdpEndpoint `
                    -SolverStatus $apiStatus.captcha_solver -FallbackUrl $StartUrl -Port $Port -ProfileDir $ProfileDir
            }
            catch { Write-Warning 'The required list authentication page is not available yet; recovery remains pending.' }
            break
        }
    }
    Write-Output "PC1 verification remains pending (probe exit $probeExit); no snapshot was published."
    exit 0
}

$cookies = Get-Content -LiteralPath $OutputPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($cookies.Count -le 0) {
    throw "PC1 authentication snapshot is empty."
}
$digest = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
$ready = Invoke-RecoveryRequest -Action snapshot_ready `
    -Body @{
        recovery_id = $recoveryId
        sha256 = $digest
        cookie_count = $cookies.Count
        created_at_epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    }
if (-not $ready.ok) {
    exit 1
}
$newState["status"] = "snapshot_published"
$newState["cookie_count"] = $cookies.Count
$newState["snapshot_sha256"] = $digest
Write-State -Path $statePath -State $newState
Write-Output "Published validated PC1 authentication metadata for recovery $recoveryId without cookie values."
