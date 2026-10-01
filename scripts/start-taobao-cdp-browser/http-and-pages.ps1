function Resolve-FapaiDataRoot {
    return Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $script:TaobaoCdpBrowserScriptRoot "..") -ExplicitRoot $DataRoot
}

function Invoke-CdpWebRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [ValidateSet("GET", "PUT")][string]$Method = "GET",
        [int]$TimeoutSec = 3,
        [int]$MaxResponseBytes = 1048576
    )

    $timeoutMilliseconds = [Math]::Max($TimeoutSec, 1) * 1000
    $request = [System.Net.HttpWebRequest]::Create($Uri)
    $request.Method = $Method
    $request.Proxy = $null
    $request.Timeout = $timeoutMilliseconds
    $request.ReadWriteTimeout = $timeoutMilliseconds
    $request.KeepAlive = $false
    if ($Method -eq "PUT") {
        $request.ContentLength = 0
    }

    $response = $null
    try {
        $response = [System.Net.HttpWebResponse]$request.GetResponse()
        $stream = $response.GetResponseStream()
        try {
            if ($stream.CanTimeout) {
                $stream.ReadTimeout = $timeoutMilliseconds
            }

            $expectedLength = [int64]$response.ContentLength
            if ($expectedLength -gt $MaxResponseBytes) {
                throw "CDP response exceeds the configured limit of $MaxResponseBytes bytes."
            }

            $readLimit = if ($expectedLength -ge 0) {
                $expectedLength
            }
            else {
                [int64]$MaxResponseBytes
            }

            $buffer = New-Object byte[] 8192
            $memory = New-Object System.IO.MemoryStream
            try {
                while ($memory.Length -lt $readLimit) {
                    $remaining = [int][Math]::Min(
                        [int64]$buffer.Length,
                        $readLimit - $memory.Length
                    )
                    if ($remaining -le 0) {
                        break
                    }

                    $read = $stream.Read($buffer, 0, $remaining)
                    if ($read -le 0) {
                        break
                    }
                    $memory.Write($buffer, 0, $read)
                }

                if ($expectedLength -ge 0 -and $memory.Length -lt $expectedLength) {
                    throw "CDP response ended before its advertised content length."
                }

                $content = [System.Text.Encoding]::UTF8.GetString($memory.ToArray())
            }
            finally {
                $memory.Dispose()
            }
        }
        finally {
            $stream.Dispose()
        }

        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Content = $content
        }
    }
    finally {
        if ($null -ne $response) {
            $response.Close()
        }
    }
}

function Test-CdpEndpoint {
    param([Parameter(Mandatory = $true)][string]$Endpoint)

    try {
        $response = Invoke-CdpWebRequest -Uri "$($Endpoint.TrimEnd('/'))/json/version" -TimeoutSec 3
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Wait-CdpEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [int]$TimeoutSeconds = 30,
        [int]$PollMilliseconds = 500
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-CdpEndpoint -Endpoint $Endpoint) {
            return $true
        }
        Start-Sleep -Milliseconds $PollMilliseconds
    }

    return $false
}

function Get-CdpPageScope {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $parsed = [Uri]$Url
        $host = $parsed.Host.ToLowerInvariant()
        $path = $parsed.AbsolutePath.ToLowerInvariant()
        while ($path.Contains('//')) { $path = $path.Replace('//', '/') }
        if ($host -eq 'sf-item.taobao.com' -or $path.Contains('/sf_item/')) {
            return 'detail'
        }
        if (($host -eq 'sf.taobao.com' -and $path.Contains('/list/')) -or
            ($path.Contains('/list/') -and $path.Contains('/punish'))) {
            return 'seed'
        }
    }
    catch {
    }
    return ''
}

function Open-CdpBrowserPage {
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][string]$Url
    )

    $baseEndpoint = $Endpoint.TrimEnd('/')

    # Authentication/challenge pages are operator-facing state.  Never create
    # a second tab when one already exists: a new login tab invalidates the QR
    # or password flow in the first tab.  This check is deliberately performed
    # while the caller holds the per-port startup mutex, so concurrent watchdog
    # invocations share one find-or-create critical section.
    try {
        $targetsResponse = Invoke-CdpWebRequest -Uri "$baseEndpoint/json/list" -TimeoutSec 5
        $targets = @($targetsResponse.Content | ConvertFrom-Json)
        $requested = [Uri]$Url
        $requestedPath = $requested.AbsolutePath
        while ($requestedPath.Contains('//')) { $requestedPath = $requestedPath.Replace('//', '/') }
        $requestedIsLogin = $requested.Host.ToLowerInvariant().Contains('login.taobao.com') -or
            $requested.Host.ToLowerInvariant().Contains('login.tmall.com') -or
            $requestedPath.ToLowerInvariant().Contains('havanaone/login')
        $requestedRoute = ($requestedPath.ToLowerInvariant() -split '/_____tmd_____/')[0]
        $requestedScope = Get-CdpPageScope -Url $Url
        foreach ($candidate in $targets) {
            if ([string]$candidate.type -ne 'page') { continue }
            $candidateUrl = [string]$candidate.url
            if (-not $candidateUrl) { continue }
            $candidateParsed = $null
            try { $candidateParsed = [Uri]$candidateUrl } catch { continue }
            $candidatePath = $candidateParsed.AbsolutePath.ToLowerInvariant()
            while ($candidatePath.Contains('//')) { $candidatePath = $candidatePath.Replace('//', '/') }
            $candidateIsLogin = $candidateParsed.Host.ToLowerInvariant().Contains('login.taobao.com') -or
                $candidateParsed.Host.ToLowerInvariant().Contains('login.tmall.com') -or
                $candidatePath.Contains('havanaone/login')
            $candidateIsChallenge = $candidateUrl.ToLowerInvariant().Contains('_____tmd_____') -or
                $candidateUrl.ToLowerInvariant().Contains('x5secdata=') -or
                $candidateUrl.ToLowerInvariant().Contains('x5step=') -or
                $candidateUrl.ToLowerInvariant().Contains('__captcha_solver_bg=1')
            $candidateRoute = ($candidatePath -split '/_____tmd_____/')[0]
            $sameRoute = $requestedRoute -and ($candidateRoute -eq $requestedRoute)
            $candidateScope = Get-CdpPageScope -Url $candidateUrl
            $sameScope = $requestedScope -and ($candidateScope -eq $requestedScope)
            if (($requestedIsLogin -and $candidateIsLogin) -or
                (-not $requestedIsLogin -and $candidateIsChallenge -and
                    ($sameScope -or (-not $requestedScope -and $sameRoute)))) {
                if ($candidate.id) {
                    try { Invoke-CdpWebRequest -Uri "$baseEndpoint/json/activate/$($candidate.id)" -TimeoutSec 3 | Out-Null } catch {}
                }
                Write-Output "Reused existing auth/challenge page: $candidateUrl"
                return
            }
        }
    }
    catch {
        Write-Host "Could not inspect existing auth/challenge pages before opening: $($_.Exception.Message)"
    }

    if (Test-BrowserProcessOpenPreferred -Url $Url) {
        throw "Skipping CDP /json/new for challenge-sized auth URL; use browser process fallback."
    }

    $encodedUrl = [System.Uri]::EscapeDataString($Url)
    $response = Invoke-CdpWebRequest -Method 'PUT' -Uri "$baseEndpoint/json/new?$encodedUrl" -TimeoutSec 10
    $page = $response.Content | ConvertFrom-Json

    if ($page.id) {
        try {
            Invoke-CdpWebRequest -Uri "$baseEndpoint/json/activate/$($page.id)" -TimeoutSec 3 | Out-Null
        }
        catch {
            Write-Host "Opened page but could not activate tab $($page.id): $($_.Exception.Message)"
        }
    }

    Write-Output "Opened auth page in existing CDP browser: $Url"
}
