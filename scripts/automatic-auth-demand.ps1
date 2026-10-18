function Test-CrowAutomaticAuthDemand {
    param([string]$ApiBase = '')
    try {
        if (-not $ApiBase) { $ApiBase = Get-CrowEnvironmentValue -Name 'CROW_COLLECTOR_API_BASE' }
        if (-not $ApiBase) { $ApiBase = Get-CrowEnvironmentValue -Name 'CROW_API_BASE_URL' }
        if (-not $ApiBase) { return $false }
        $origin = ConvertTo-CollectionApiOrigin $ApiBase
        $status = Invoke-RestMethod -Uri "$origin/api/status" -TimeoutSec 5
        return $status.auth_recovery.automatic_auth_allowed -eq $true
    } catch { return $false }
}
