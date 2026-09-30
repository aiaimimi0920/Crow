param(
    [int]$Port = 9223,
    [string]$DataRoot = "",
    [string]$OutputPath = "",
    [string]$Python = "python",
    [string[]]$SampleUrl = @(
        "https://sf.taobao.com/list/50025969__2.htm",
        "https://sf.taobao.com/list/200782003__1.htm"
    ),
    [string[]]$DetailSampleUrl = @(),
    [switch]$StartBrowser,
    [switch]$SkipBrowserStart,
    [switch]$IsolatedProfile,
    [switch]$DisableExtensions
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")
$script:manualAuthStartUrl = ""

function Resolve-FapaiDataRoot {
    return Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot
}

function Test-CdpEndpoint {
    param([Parameter(Mandatory = $true)][string]$Endpoint)

    try {
        $response = Invoke-WebRequest -Uri "$($Endpoint.TrimEnd('/'))/json/version" -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function ConvertTo-CanonicalDetailSampleUrl {
    param([string]$Url)

    if (-not $Url) {
        return ""
    }
    try {
        $uri = [Uri]$Url
    }
    catch {
        return ""
    }
    if ($uri.Host -notin @("sf-item.taobao.com", "sf.taobao.com")) {
        return ""
    }
    $match = [regex]::Match($uri.AbsolutePath, "/sf_item/(\d+)\.htm", "IgnoreCase")
    if (-not $match.Success) {
        return ""
    }
    return "https://sf-item.taobao.com/sf_item/$($match.Groups[1].Value).htm"
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

function Complete-ManualBrowserHandoff {
    param(
        [Parameter(Mandatory = $true)][string]$ResolvedDataRoot,
        [Parameter(Mandatory = $true)][int]$ResolvedPort
    )

    $manualStatePath = Join-Path $ResolvedDataRoot "secrets\pc1-manual-auth-state.json"
    if (-not (Test-Path -LiteralPath $manualStatePath)) {
        return $false
    }

    $manualState = Get-Content -LiteralPath $manualStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$manualState.mode -ne "manual_browser_without_cdp") {
        throw "Unexpected PC1 manual-auth state mode."
    }
    $profileDir = [string]$manualState.profile_dir
    $browserPath = [string]$manualState.browser_path
    if (-not $profileDir -or -not $browserPath) {
        throw "PC1 manual-auth state is missing browser profile information."
    }
    if ($manualState.PSObject.Properties.Name -contains "start_url") {
        $script:manualAuthStartUrl = [string]$manualState.start_url
    }

    $roots = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -eq "chrome.exe" -and
                ($_.CommandLine -like "*$profileDir*" -or [int]$_.ProcessId -eq [int]$manualState.process_id)
            }
    )
    foreach ($processId in @(Get-ProcessTreeIds -RootIds @($roots.ProcessId) | Sort-Object -Descending -Unique)) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3

    $bridgeScript = Join-Path $PSScriptRoot "start-pc1-auth-bridge.ps1"
    if (-not (Test-Path -LiteralPath $bridgeScript)) {
        throw "Missing PC1 auth bridge script: $bridgeScript"
    }
    & powershell.exe `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $bridgeScript `
        -LocalCdpPort $ResolvedPort `
        -RemoteCdpPort $(if ($env:FAPAI_AUTH_REMOTE_CDP_PORT) { [int]$env:FAPAI_AUTH_REMOTE_CDP_PORT } else { 9225 }) `
        -ProfileDir $profileDir `
        -BrowserPath $browserPath `
        -DataRoot $ResolvedDataRoot `
        -StartUrl "about:blank"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to restore the PC1 CDP bridge after manual authentication."
    }
    Remove-Item -LiteralPath $manualStatePath -Force
    return $true
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$previousPythonPath = $env:PYTHONPATH
if ($previousPythonPath) {
    $env:PYTHONPATH = "$repoRoot;$previousPythonPath"
}
else {
    $env:PYTHONPATH = $repoRoot
}

$dataRootResolved = Resolve-FapaiDataRoot
if (-not $OutputPath) {
    $OutputPath = if ($env:FAPAI_COOKIE_SNAPSHOT) {
        $env:FAPAI_COOKIE_SNAPSHOT
    } else {
        Join-Path $dataRootResolved "secrets\taobao-cookies.json"
    }
}

$resolvedPort = if ($env:FAPAI_AUTH_LOCAL_CDP_PORT) {
    [int]$env:FAPAI_AUTH_LOCAL_CDP_PORT
} else {
    $Port
}
$cdpEndpoint = if ($env:FAPAI_AUTH_LOCAL_CDP_ENDPOINT) {
    $env:FAPAI_AUTH_LOCAL_CDP_ENDPOINT.TrimEnd('/')
} else {
    "http://127.0.0.1:$resolvedPort"
}
$manualHandoffCompleted = Complete-ManualBrowserHandoff `
    -ResolvedDataRoot $dataRootResolved `
    -ResolvedPort $resolvedPort
$detailSampleUrls = @(
    @($DetailSampleUrl) + @(ConvertTo-CanonicalDetailSampleUrl -Url $script:manualAuthStartUrl) |
        ForEach-Object { ConvertTo-CanonicalDetailSampleUrl -Url ([string]$_) } |
        Where-Object { $_ } |
        Select-Object -Unique
)
$startScript = Join-Path $repoRoot "scripts\start-taobao-cdp-browser.ps1"
$probeScript = Join-Path $repoRoot "tools\browserless_seed_probe.py"

if (-not (Test-Path -LiteralPath $probeScript)) {
    throw "Missing browserless seed probe helper: $probeScript"
}

if (-not $SkipBrowserStart) {
    $shouldStart = $StartBrowser -or -not (Test-CdpEndpoint -Endpoint $cdpEndpoint)
    if ($shouldStart) {
        $startArgs = @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $startScript,
            "-Port",
            $Port
        )
        if ($DataRoot) {
            $startArgs += @("-DataRoot", $DataRoot)
        }
        if ($IsolatedProfile) {
            $startArgs += @("-IsolatedProfile")
        }
        if ($DisableExtensions) {
            $startArgs += @("-DisableExtensions")
        }
        & powershell @startArgs
    }
}

$outputParent = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outputParent | Out-Null
$candidatePath = Join-Path $outputParent ("taobao-cookies.candidate." + [guid]::NewGuid().ToString() + ".json")

$helperOutput = Join-Path $env:TEMP ("fpf-cookie-export-" + [guid]::NewGuid().ToString() + ".jsonlog")
try {
    & $Python $probeScript `
        --cdp-endpoint $cdpEndpoint `
        --write-cookie-snapshot $candidatePath `
        *> $helperOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Cookie snapshot export helper failed with exit code $LASTEXITCODE. Helper output was not printed to avoid leaking Taobao security tokens or cookie values."
    }
}
finally {
    Remove-Item -LiteralPath $helperOutput -Force -ErrorAction SilentlyContinue
}

$validationScript = Join-Path $env:TEMP ("fpf-cookie-candidate-health-" + [guid]::NewGuid().ToString() + ".py")
$validationOutput = Join-Path $env:TEMP ("fpf-cookie-candidate-health-" + [guid]::NewGuid().ToString() + ".jsonlog")
try {
    @'
import json
import os
import sys
from pathlib import Path
from tools import browserless_seed_probe, live_batch_smoke, taobao_login_health

path = Path(os.environ["FAPAI_COOKIE_SNAPSHOT_CANDIDATE"])
sample_urls = json.loads(os.environ["FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS_JSON"])
detail_sample_urls = json.loads(os.environ["FAPAI_COOKIE_SNAPSHOT_DETAIL_SAMPLE_URLS_JSON"])
cookies = browserless_seed_probe.load_cookie_snapshot(path)
session = browserless_seed_probe.build_session_from_playwright_cookies(cookies)
cookie_summary = browserless_seed_probe.summarize_cookie_snapshot(cookies)
cookie_summary.pop("names", None)
sample_results = []
cookie_http_healthy_samples = 0
for url in sample_urls:
    summary = browserless_seed_probe.probe_seed_page(url, cookies=cookies, session=session, timeout=15)
    classification = taobao_login_health.classify_taobao_health(
        "",
        final_url=str(summary.get("final_url") or url),
        list_summary=summary,
        payload_present=summary.get("has_script") is True,
    )
    result = {
        "check_url": url,
        "status": classification["status"],
        "healthy": classification["healthy"],
        "final_url": classification["final_url"],
        "http_status": summary.get("status"),
        "has_script": summary.get("has_script"),
        "item_count": summary.get("item_count"),
        "body_has_login": summary.get("body_has_login"),
        "body_has_captcha": summary.get("body_has_captcha"),
        "body_has_punish": summary.get("body_has_punish"),
        "body_has_challenge": summary.get("body_has_challenge"),
    }
    if result["healthy"] is True:
        cookie_http_healthy_samples += 1
    sample_results.append(result)

browser_page_healthy_samples = 0
if cookie_http_healthy_samples == 0:
    cdp_endpoint = os.environ["FAPAI_COOKIE_SNAPSHOT_CDP_ENDPOINT"]
    for url in sample_urls:
        browser_page = live_batch_smoke.fetch_open_browser_list_page(cdp_endpoint, url)
        if browser_page is None:
            continue
        html, final_url = browser_page
        list_summary, payload_present = taobao_login_health._probe_summary_and_payload(html, final_url)
        classification = taobao_login_health.classify_taobao_health(
            html,
            final_url=final_url,
            list_summary=list_summary,
            payload_present=payload_present,
        )
        result = {
            "check_url": url,
            "status": classification["status"],
            "healthy": classification["healthy"],
            "final_url": classification["final_url"],
            "probe_transport": "existing_cdp_page",
            "has_script": list_summary.get("has_script"),
            "item_count": list_summary.get("item_count"),
        }
        if result["healthy"] is True:
            browser_page_healthy_samples += 1
        sample_results.append(result)

healthy_samples = cookie_http_healthy_samples + browser_page_healthy_samples
detail_sample_results = []
detail_healthy_samples = 0
cdp_endpoint = os.environ["FAPAI_COOKIE_SNAPSHOT_CDP_ENDPOINT"]
for url in detail_sample_urls:
    result = {
        "check_scope": "detail",
        "status": "detail_http_error",
        "healthy": False,
        "http_status": None,
        "probe_transport": "cookie_http",
    }
    try:
        response = session.get(
            url,
            headers={
                "User-Agent": browserless_seed_probe.DEFAULT_USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://sf.taobao.com/",
            },
            timeout=30,
            allow_redirects=True,
        )
        result["http_status"] = response.status_code
        response.raise_for_status()
        result["healthy"] = not live_batch_smoke.is_challenge_page(response.text, response.url)
        result["status"] = "healthy_detail_payload" if result["healthy"] else "detail_challenge_page"
    except Exception:
        pass

    if result["healthy"] is not True:
        try:
            live_batch_smoke.fetch_detail_with_browser(
                {"id": "auth-validation", "url": url},
                cdp_endpoint=cdp_endpoint,
            )
        except Exception:
            result["status"] = "detail_browser_challenge_or_error"
            result["probe_transport"] = "cdp_browser"
        else:
            result["status"] = "healthy_detail_payload"
            result["healthy"] = True
            result["probe_transport"] = "cdp_browser"

    if result["healthy"] is True:
        detail_healthy_samples += 1
    detail_sample_results.append(result)

detail_health_required = len(detail_sample_urls) > 0
detail_health_satisfied = not detail_health_required or detail_healthy_samples == len(detail_sample_urls)
payload = {
    "candidate_path": str(path),
    "cookie_summary": cookie_summary,
    "sample_count": len(sample_results),
    "healthy_samples": healthy_samples,
    "cookie_http_healthy_samples": cookie_http_healthy_samples,
    "browser_page_healthy_samples": browser_page_healthy_samples,
    "browser_required": cookie_http_healthy_samples == 0 and browser_page_healthy_samples > 0,
    "detail_sample_count": len(detail_sample_results),
    "detail_healthy_samples": detail_healthy_samples,
    "detail_health_required": detail_health_required,
    "detail_health_satisfied": detail_health_satisfied,
    "healthy": healthy_samples > 0 and detail_health_satisfied,
    "sample_results": sample_results,
    "detail_sample_results": detail_sample_results,
}
public_payload = taobao_login_health.redact_taobao_health_output(payload)
public_payload.pop("candidate_path", None)
public_payload.pop("cookie_summary", None)
print(json.dumps(public_payload, ensure_ascii=False))
sys.exit(0 if payload["healthy"] else 2)
'@ | Set-Content -LiteralPath $validationScript -Encoding UTF8
    $env:FAPAI_COOKIE_SNAPSHOT_CANDIDATE = $candidatePath
    $env:FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS_JSON = ConvertTo-Json -InputObject @($SampleUrl) -Compress
    $env:FAPAI_COOKIE_SNAPSHOT_DETAIL_SAMPLE_URLS_JSON = ConvertTo-Json -InputObject @($detailSampleUrls) -Compress
    $env:FAPAI_COOKIE_SNAPSHOT_CDP_ENDPOINT = $cdpEndpoint
    & $Python $validationScript *> $validationOutput
    $validationJson = if (Test-Path -LiteralPath $validationOutput) { Get-Content -Raw -LiteralPath $validationOutput } else { "" }
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $candidatePath -Force -ErrorAction SilentlyContinue
        throw "Cookie snapshot candidate failed Taobao list/detail health validation; official snapshot was not overwritten. Candidate health output: $validationJson"
    }
}
finally {
    Remove-Item -LiteralPath $validationScript -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $validationOutput -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\FAPAI_COOKIE_SNAPSHOT_CANDIDATE -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS_JSON -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\FAPAI_COOKIE_SNAPSHOT_DETAIL_SAMPLE_URLS_JSON -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\FAPAI_COOKIE_SNAPSHOT_CDP_ENDPOINT -Force -ErrorAction SilentlyContinue
}

Move-Item -LiteralPath $candidatePath -Destination $OutputPath -Force

$summaryScript = Join-Path $env:TEMP ("fpf-cookie-summary-" + [guid]::NewGuid().ToString() + ".py")
$summaryOutput = Join-Path $env:TEMP ("fpf-cookie-summary-" + [guid]::NewGuid().ToString() + ".jsonlog")
try {
    @'
import json
import os
from pathlib import Path
from tools import browserless_seed_probe

path = Path(os.environ["FAPAI_COOKIE_SNAPSHOT_OUTPUT"])
cookies = browserless_seed_probe.load_cookie_snapshot(path)
summary = browserless_seed_probe.summarize_cookie_snapshot(cookies)
summary.pop('names', None)
summary['path'] = str(path)
print(json.dumps(summary, ensure_ascii=False))
'@ | Set-Content -LiteralPath $summaryScript -Encoding UTF8
    $env:FAPAI_COOKIE_SNAPSHOT_OUTPUT = $OutputPath
    & $Python $summaryScript *> $summaryOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Cookie snapshot summary failed with exit code $LASTEXITCODE. Summary helper output was not printed to avoid leaking Taobao security tokens or cookie values."
    }
    $summaryJson = Get-Content -Raw -LiteralPath $summaryOutput
}
finally {
    Remove-Item -LiteralPath $summaryScript -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $summaryOutput -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\FAPAI_COOKIE_SNAPSHOT_OUTPUT -Force -ErrorAction SilentlyContinue
}
$summary = $summaryJson | ConvertFrom-Json

Write-Output "Exported Taobao cookie snapshot without printing cookie value fields."
Write-Output "Cookie snapshot path: $OutputPath"
Write-Output "Docker worker path when using host-bind data root: /data/secrets/taobao-cookies.json"
$summary | ConvertTo-Json -Depth 6
