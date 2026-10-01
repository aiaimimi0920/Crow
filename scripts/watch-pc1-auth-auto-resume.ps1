param(
    [int]$Port = 9225,
    [string]$ApiBase = "",
    [string]$DataRoot = "",
    [string]$OutputPath = "",
    [string]$Python = "python",
    [int]$PollSeconds = 5,
    [int]$MaxWaitSeconds = 1800
)
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot 'project-environment.ps1')



. (Join-Path $PSScriptRoot "project-data-root.ps1")
$DataRoot = Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot
. (Join-Path $PSScriptRoot "collection-api-origin.ps1")

function Resolve-ApiBase {
    if ($ApiBase) {
        return (ConvertTo-CollectionApiOrigin $ApiBase) + "/api"
    }
    if ((Get-CrowEnvironmentValue -Name 'CROW_COLLECTOR_API_BASE')) {
        return (ConvertTo-CollectionApiOrigin (Get-CrowEnvironmentValue -Name 'CROW_COLLECTOR_API_BASE')) + "/api"
    }
    if ((Get-CrowEnvironmentValue -Name 'CROW_API_BASE_URL')) {
        return (ConvertTo-CollectionApiOrigin (Get-CrowEnvironmentValue -Name 'CROW_API_BASE_URL')) + "/api"
    }
    throw "An explicit HTTPS API origin or protected loopback tunnel is required."
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
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Append-LogLine {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Message
    )

    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $Path -Value $line -Encoding UTF8
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$completeScript = Join-Path $repoRoot "scripts\complete-pc1-inplace-auth.ps1"
if (-not (Test-Path -LiteralPath $completeScript)) {
    throw "Missing complete-pc1-inplace-auth.ps1"
}

if (-not $OutputPath) {
    $OutputPath = if ((Get-CrowEnvironmentValue -Name 'CROW_COOKIE_SNAPSHOT' -PathValue)) { (Get-CrowEnvironmentValue -Name 'CROW_COOKIE_SNAPSHOT' -PathValue) } else { Join-Path $DataRoot "secrets\nodes\pc2\taobao-cookies.json" }
}

$stateDir = Join-Path $DataRoot "secrets"
$statePath = Join-Path $stateDir "pc1-auth-auto-resume-state.json"
$logPath = Join-Path $stateDir "pc1-auth-auto-resume.log"
$apiBaseResolved = Resolve-ApiBase

$state = [ordered]@{
    mode = "pc1_auth_auto_resume_watch"
    api_base = $apiBaseResolved
    cdp_endpoint = "http://127.0.0.1:$Port"
    output_path = $OutputPath
    poll_seconds = $PollSeconds
    max_wait_seconds = $MaxWaitSeconds
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    status = "watching"
}
Write-Utf8NoBomFile -Path $statePath -Content (($state | ConvertTo-Json -Depth 4))
Append-LogLine -Path $logPath -Message "started watcher for $apiBaseResolved"

$deadline = (Get-Date).AddSeconds([Math]::Max($MaxWaitSeconds, 30))
$lastError = ""

while ((Get-Date) -lt $deadline) {
    try {
        & powershell.exe `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $completeScript `
            -Port $Port `
            -DataRoot $DataRoot `
            -OutputPath $OutputPath `
            -Python $Python `
            -AllowListOnly
        if ($LASTEXITCODE -eq 0) {
            $body = @{
                source = "pc1_auth_auto_resume_watch"
                refresh_cookie_snapshot = $false
            } | ConvertTo-Json -Compress
            Invoke-RestMethod `
                -Uri "$apiBaseResolved/collection/auth/complete" `
                -Method Post `
                -ContentType "application/json" `
                -Body $body `
                -TimeoutSec 15 | Out-Null
            $state.status = "completed"
            $state.completed_at = (Get-Date).ToUniversalTime().ToString("o")
            Write-Utf8NoBomFile -Path $statePath -Content (($state | ConvertTo-Json -Depth 4))
            Append-LogLine -Path $logPath -Message "cookie health passed; auth_complete posted"
            exit 0
        }
        $lastError = "cookie export returned non-zero exit code"
    }
    catch {
        $lastError = $_.Exception.Message
    }
    if ($lastError) {
        Append-LogLine -Path $logPath -Message "not ready yet: $lastError"
    }
    Start-Sleep -Seconds ([Math]::Max($PollSeconds, 1))
}

$state.status = "timed_out"
$state.completed_at = (Get-Date).ToUniversalTime().ToString("o")
$state.last_error = $lastError
Write-Utf8NoBomFile -Path $statePath -Content (($state | ConvertTo-Json -Depth 4))
Append-LogLine -Path $logPath -Message "timed out waiting for reusable auth"
exit 2
