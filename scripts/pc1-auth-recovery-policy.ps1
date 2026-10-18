function Get-Pc1RecoveryDetailUrl {
    param([string]$Value)

    try {
        $uri = [Uri]$Value
        if ($uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Port -ne 443) { return '' }
        $pattern = switch ($uri.Host) {
            'sf-item.taobao.com' { '^/sf_item/(\d+)\.htm$' }
            'susong-item.taobao.com' { '^/auction/(\d+)\.htm$' }
            default { '' }
        }
        $path = ($uri.AbsolutePath -replace '/+', '/') -split '/_____tmd_____/'
        if ($pattern -and $path[0] -match $pattern) {
            return "https://sf-item.taobao.com/sf_item/$($Matches[1]).htm"
        }
    }
    catch { }
    return ''
}

function Get-Pc1RecoveryTargetUrl {
    param($SolverStatus, [Parameter(Mandatory = $true)][string]$FallbackUrl)

    $detail = $SolverStatus.scopes.detail.last_request
    foreach ($request in @($detail, $SolverStatus.last_request)) {
        foreach ($value in @($request.target_url, $request.url)) {
            $detailUrl = Get-Pc1RecoveryDetailUrl -Value $value
            if ($detailUrl) { return $detailUrl }
        }
    }
    return $FallbackUrl
}

function Get-Pc1RecoverySeedUrl {
    param([string]$Value)

    try {
        $uri = [Uri]$Value
        if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'sf.taobao.com' -or
            $uri.UserInfo -or $uri.Port -ne 443) { return '' }
        $path = (($uri.AbsolutePath -replace '/+', '/') -split '/_____tmd_____/')[0]
        if ($path -notmatch '^/list/[\w-]+\.htm$') { return '' }
        $pairs = @(foreach ($part in $uri.Query.TrimStart('?').Split('&')) {
            $entry = $part.Split('=', 2)
            $key = [Uri]::UnescapeDataString($entry[0].Replace('+', ' '))
            if ($entry.Count -eq 2 -and $key -cin @('location_code', 'st_param', 'auction_start_seg', 'page')) {
                $valuePart = [Uri]::UnescapeDataString($entry[1].Replace('+', ' '))
                [Uri]::EscapeDataString($key) + '=' + [Uri]::EscapeDataString($valuePart)
            }
        })
        $query = if ($pairs.Count) { '?' + (($pairs | Sort-Object) -join '&') } else { '' }
        return "https://sf.taobao.com$path$query"
    }
    catch { return '' }
}

function Test-Pc1RecoveryChallengeTab {
    param($Tab)
    # Inline verification may retain the normal detail URL; CDP still exposes its title.
    return [string]$Tab.url -match '_____tmd_____/|x5secdata=|x5step=' -or
        [string]$Tab.title -match 'captcha|verification|\u9a8c\u8bc1'
}

function Get-Pc1RecoveryTab {
    param($Tabs, [string]$PreferredId, [Parameter(Mandatory = $true)][string]$TargetUrl)

    $pages = @($Tabs | Where-Object {
        try {
            $hostName = ([Uri]$_.url).Host
            [string]$_.type -eq 'page' -and
                ($hostName -eq 'taobao.com' -or $hostName.EndsWith('.taobao.com'))
        }
        catch { $false }
    })
    if ($PreferredId) {
        $existing = @($pages | Where-Object { [string]$_.id -eq $PreferredId })
        if ($existing.Count) { return $existing[0] }
    }
    $route = ([Uri]$TargetUrl).AbsolutePath -replace '/+', '/'
    $targetHost = ([Uri]$TargetUrl).Host
    $detailTarget = Get-Pc1RecoveryDetailUrl -Value $TargetUrl
    $seedTarget = Get-Pc1RecoverySeedUrl -Value $TargetUrl
    $matching = @($pages | Where-Object {
        if ($detailTarget) {
            (Get-Pc1RecoveryDetailUrl -Value $_.url) -eq $detailTarget
        }
        elseif ($seedTarget) {
            (Get-Pc1RecoverySeedUrl -Value $_.url) -ceq $seedTarget
        }
        else {
            $uri = [Uri]$_.url
            $path = ($uri.AbsolutePath -replace '/+', '/') -split '/_____tmd_____/'
            $uri.Host -eq $targetHost -and $path[0] -eq $route
        }
    })
    if ($matching.Count) {
        $challenge = @($matching | Where-Object { Test-Pc1RecoveryChallengeTab -Tab $_ })
        if ($challenge.Count) { return $challenge[0] }
        return $matching[0]
    }
    # Keep an in-flight login or detail challenge instead of replacing human work.
    $interactive = @($pages | Where-Object {
        $uri = [Uri]$_.url
        $uri.Host -eq 'login.taobao.com' -or
            ($detailTarget -and (Get-Pc1RecoveryDetailUrl -Value $_.url) -and
                (Test-Pc1RecoveryChallengeTab -Tab $_))
    })
    if ($interactive.Count) { return $interactive[0] }
    return $null
}

function Wait-Pc1RecoveryTab {
    param([string]$Endpoint, [string]$TargetUrl, [int]$TimeoutSeconds = 15)
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds([Math]::Max($TimeoutSeconds, 1))
    do {
        try {
            $tabs = (Invoke-CdpWebRequest -Uri "$Endpoint/json/list" -TimeoutSec 3).Content | ConvertFrom-Json
            $tab = Get-Pc1RecoveryTab -Tabs $tabs -TargetUrl $TargetUrl
            if ($null -ne $tab) { return $tab }
        }
        catch { }
        Start-Sleep -Milliseconds 500
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    return $null
}

function Test-Pc1RecoveryPromptDue {
    param([bool]$SameRecovery, [string]$PromptedAt)
    # Background polling must not repeatedly interrupt an unfinished human check.
    return -not $SameRecovery -or [string]::IsNullOrWhiteSpace($PromptedAt)
}

function Show-Pc1RecoveryPrompt {
    param([string]$Endpoint, [string]$TargetId, [int]$Port, [string]$ProfileDir)

    $result = [ordered]@{ tab_activated = $false; window_shown = $false }
    try {
        if ($TargetId) {
            Invoke-CdpWebRequest -Uri "$Endpoint/json/activate/$TargetId" -TimeoutSec 3 | Out-Null
            $result.tab_activated = $true
        }
        Show-CdpBrowserWindow -Port $Port -ProfileDir $ProfileDir
        $result.window_shown = $true
    }
    catch { Write-Warning "Could not foreground the dedicated auth window; preserving the recovery state." }
    return [pscustomobject]$result
}

function Show-Pc1RecoverySeedPrompt {
    param($State, [string]$StatePath, [string]$Endpoint, $SolverStatus,
          [string]$FallbackUrl, [int]$Port, [string]$ProfileDir,
          [switch]$DeferPresentation)

    $request = $SolverStatus.scopes.seed.last_request
    $seedUrl = ''
    foreach ($value in @($State.seed_target_url, $request.challenge_target_url,
                         $request.target_url, $request.url, $FallbackUrl)) {
        $seedUrl = Get-Pc1RecoverySeedUrl -Value $value
        if ($seedUrl) { break }
    }
    if (-not $seedUrl) { throw 'No valid seed authentication target is available.' }
    $State['status'] = 'waiting_for_seed_auth'
    $State['seed_target_url'] = $seedUrl
    # A main prompt for this same list target already consumes the seed prompt.
    if ($State.prompted_at -and (Get-Pc1RecoverySeedUrl -Value $State.target_url) -eq $seedUrl) {
        $State['seed_prompted_at'] = $State.prompted_at
        $State['seed_target_id'] = $State.target_id
    }
    if ($DeferPresentation) {
        # Do not create/activate another tab immediately after the main presentation.
        Write-State -Path $StatePath -State $State
        return
    }
    $tabs = @(Get-CdpTabs -Endpoint $Endpoint)
    $tab = Get-Pc1RecoveryTab -Tabs $tabs -PreferredId $State.seed_target_id -TargetUrl $seedUrl
    if ($null -eq $tab) {
        $response = Invoke-CdpWebRequest -Method PUT -TimeoutSec 3 `
            -Uri "$($Endpoint.TrimEnd('/'))/json/new?$([Uri]::EscapeDataString($seedUrl))"
        $tab = $response.Content | ConvertFrom-Json
    }
    if (-not $tab.id) { throw 'The seed authentication tab was not created.' }
    $State['status'] = 'waiting_for_seed_auth'
    $State['seed_target_url'] = $seedUrl
    $State['seed_target_id'] = [string]$tab.id
    if (-not $State.seed_prompted_at) {
        $State['seed_prompted_at'] = [DateTimeOffset]::UtcNow.ToString('o')
        Write-State -Path $StatePath -State $State
        Show-Pc1RecoveryPrompt -Endpoint $Endpoint -TargetId $tab.id -Port $Port -ProfileDir $ProfileDir | Out-Null
    }
    Write-State -Path $StatePath -State $State
}
