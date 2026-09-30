
. (Join-Path $PSScriptRoot '..\project-environment.ps1')

function Write-JsonLine {
    param([Parameter(Mandatory = $true)]$Value)

    $Value | ConvertTo-Json -Compress -Depth 8
}

function Send-OperationalAlert {
    param(
        [Parameter(Mandatory = $true)][string]$EventName,
        [Parameter(Mandatory = $true)][hashtable]$Payload
    )

    if (-not $resolvedAlertWebhookUrl) {
        return
    }
    try {
        $body = [ordered]@{
            source = "trigger-taobao-login-recovery-if-needed"
            event = $EventName
            observed_at = (Get-Date).ToString("o")
            host = $env:COMPUTERNAME
            payload = $Payload
        } | ConvertTo-Json -Depth 8 -Compress
        Invoke-RestMethod `
            -Uri $resolvedAlertWebhookUrl `
            -Method Post `
            -ContentType "application/json" `
            -Body $body `
            -TimeoutSec 10 | Out-Null
    }
    catch {
        Write-Warning ("Operational alert delivery failed: {0}" -f $_.Exception.Message)
    }
}

function Read-RecoveryState {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return @{}
    }

    try {
        $raw = Get-Content -Raw -LiteralPath $Path
        if (-not $raw) {
            return @{}
        }
        return $raw | ConvertFrom-Json
    }
    catch {
        return @{}
    }
}

function Write-RecoveryState {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][datetime]$LastTriggeredAt,
        [Parameter(Mandatory = $true)][object]$Snapshot
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    @{
        LastTriggeredAt = $LastTriggeredAt.ToString("o")
        Snapshot = $Snapshot
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-ManualAuthObservationPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return "$Path.manual-observation.json"
}

function Read-ManualAuthObservation {
    param([Parameter(Mandatory = $true)][string]$Path)

    return Read-RecoveryState -Path (Get-ManualAuthObservationPath -Path $Path)
}

function Write-ManualAuthObservation {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][datetime]$ManualRequiredSince,
        [Parameter(Mandatory = $true)][object]$Snapshot
    )

    $observationPath = Get-ManualAuthObservationPath -Path $Path
    $parent = Split-Path -Parent $observationPath
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    @{
        ManualRequiredSince = $ManualRequiredSince.ToString("o")
        Snapshot = $Snapshot
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $observationPath -Encoding UTF8
}

function Clear-ManualAuthObservation {
    param([Parameter(Mandatory = $true)][string]$Path)

    Remove-Item -LiteralPath (Get-ManualAuthObservationPath -Path $Path) -Force -ErrorAction SilentlyContinue
}

function Stop-DedicatedRecoveryBrowser {
    $rootProcesses = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -in @("msedge.exe", "chrome.exe") -and
                [string]$_.CommandLine -match "remote-debugging-port=9225" -and
                [string]$_.CommandLine -notmatch "--type="
            }
    )
    foreach ($process in $rootProcesses) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    return $rootProcesses.Count
}

function Get-NullableInt {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }
    return [int]$Value
}

function Get-NullableDouble {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }
    return [double]$Value
}

function Resolve-ApiBaseUrl {
    param([string]$Value)

    $candidate = if ($Value) {
        $Value
    } elseif ((Get-CrowEnvironmentValue -Name 'CROW_API_BASE_URL')) {
        (Get-CrowEnvironmentValue -Name 'CROW_API_BASE_URL')
    } elseif ((Get-CrowEnvironmentValue -Name 'CROW_CENTRAL_API_BASE_URL')) {
        (Get-CrowEnvironmentValue -Name 'CROW_CENTRAL_API_BASE_URL')
    } else {
        throw "An explicit HTTPS API origin or protected loopback tunnel is required."
    }
    . (Join-Path $PSScriptRoot "..\collection-api-origin.ps1")
    return ((ConvertTo-CollectionApiOrigin ([string]$candidate)) + "/api")
}
