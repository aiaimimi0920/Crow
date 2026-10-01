param(
    [string]$StartUrl = "https://sf.taobao.com/list/50025969__2.htm",
    [string]$ProfileDir = "",
    [string]$BrowserPath = "",
    [string]$DataRoot = "",
    [int]$CdpPort = 9225
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")

function Resolve-Setting {
    param(
        [string]$ExplicitValue,
        [string]$EnvironmentName,
        [string]$DefaultValue
    )

    if ($ExplicitValue) {
        return $ExplicitValue
    }
    $environmentValue = [Environment]::GetEnvironmentVariable($EnvironmentName, "Process")
    if ($environmentValue) {
        return $environmentValue
    }
    return $DefaultValue
}

function Get-ProcessTreeIds {
    param([int[]]$RootIds)

    $allProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $queue = New-Object "System.Collections.Generic.Queue[int]"
    $ids = New-Object "System.Collections.Generic.HashSet[int]"
    foreach ($rootId in $RootIds) {
        $queue.Enqueue($rootId)
    }
    while ($queue.Count -gt 0) {
        $processId = $queue.Dequeue()
        if (-not $ids.Add($processId)) {
            continue
        }
        foreach ($child in @($allProcesses | Where-Object { [int]$_.ParentProcessId -eq $processId })) {
            $queue.Enqueue([int]$child.ProcessId)
        }
    }
    return @($ids)
}

function Stop-ProfileBrowser {
    param(
        [Parameter(Mandatory = $true)][string]$ResolvedProfileDir,
        [Parameter(Mandatory = $true)][int]$DebugPort
    )

    $roots = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -eq "chrome.exe" -and
                ($_.CommandLine -like "*$ResolvedProfileDir*" -or $_.CommandLine -match "--remote-debugging-port=$DebugPort(?:\s|$)")
            }
    )
    $treeIds = @(Get-ProcessTreeIds -RootIds @($roots.ProcessId))
    foreach ($processId in @($treeIds | Sort-Object -Descending -Unique)) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    if ($treeIds.Count -gt 0) {
        Start-Sleep -Seconds 3
    }
    return $treeIds.Count
}

$resolvedDataRoot = Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot
$resolvedProfileDir = Resolve-Setting `
    -ExplicitValue $ProfileDir `
    -EnvironmentName "FAPAI_AUTH_BROWSER_PROFILE_DIR" `
    -DefaultValue (Join-Path $resolvedDataRoot "chrome-cdp-profile-pc1-human-clean")
$resolvedBrowserPath = Resolve-Setting `
    -ExplicitValue $BrowserPath `
    -EnvironmentName "FAPAI_AUTH_BROWSER_PATH" `
    -DefaultValue "C:\Program Files\Google\Chrome\Application\chrome.exe"

if (-not (Test-Path -LiteralPath $resolvedBrowserPath)) {
    throw "Configured manual-auth browser does not exist: $resolvedBrowserPath"
}

New-Item -ItemType Directory -Force -Path $resolvedProfileDir | Out-Null
$stoppedCount = Stop-ProfileBrowser -ResolvedProfileDir $resolvedProfileDir -DebugPort $CdpPort

$browserArguments = @(
    "--user-data-dir=$resolvedProfileDir",
    "--no-first-run",
    "--no-default-browser-check",
    $StartUrl
)
$browser = Start-Process `
    -FilePath $resolvedBrowserPath `
    -ArgumentList $browserArguments `
    -WorkingDirectory (Split-Path -Parent $resolvedBrowserPath) `
    -PassThru

$stateDir = Join-Path $resolvedDataRoot "secrets"
$statePath = Join-Path $stateDir "pc1-manual-auth-state.json"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$state = [ordered]@{
    mode = "manual_browser_without_cdp"
    process_id = $browser.Id
    profile_dir = $resolvedProfileDir
    browser_path = $resolvedBrowserPath
    start_url = $StartUrl
    cdp_port = $CdpPort
    started_at = (Get-Date).ToUniversalTime().ToString("o")
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($statePath, ($state | ConvertTo-Json -Depth 3), $utf8NoBom)

Write-Output "PC1 manual-auth browser started without CDP automation."
Write-Output "Stopped prior dedicated-browser processes: $stoppedCount"
Write-Output "Complete Taobao authentication in the visible browser, then click authentication complete in the collector desktop."
