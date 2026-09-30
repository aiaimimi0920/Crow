param(
    [string]$DataRoot = "",
    [int]$Port = 9223,
    [string]$Python = "python",
    [string[]]$SampleUrl = @(
        "https://sf.taobao.com/list/50025969__2.htm",
        "https://sf.taobao.com/list/200782003__1.htm"
    ),
    [switch]$UseSystemProxy,
    [switch]$SkipLoginWatchdog,
    [switch]$SkipDockerStart,
    [switch]$Build
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")
$DataRoot = Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot

function Ensure-EnvLine {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $line = "$Key=$Value"
    if (-not (Test-Path -LiteralPath $Path)) {
        Set-Content -LiteralPath $Path -Value $line -Encoding UTF8
        return
    }
    $existing = Select-String -LiteralPath $Path -Pattern "^$([regex]::Escape($Key))=" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existing) {
        return
    }
    Add-Content -LiteralPath $Path -Value $line -Encoding UTF8
}

function Set-EnvLine {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $line = "$Key=$Value"
    if (-not (Test-Path -LiteralPath $Path)) {
        Set-Content -LiteralPath $Path -Value $line -Encoding UTF8
        return
    }

    $content = Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue
    $pattern = "^$([regex]::Escape($Key))="
    $replaced = $false
    $updated = foreach ($existingLine in $content) {
        if ($existingLine -match $pattern) {
            $replaced = $true
            $line
        }
        else {
            $existingLine
        }
    }

    if (-not $replaced) {
        $updated = @($updated) + $line
    }
    Set-Content -LiteralPath $Path -Value $updated -Encoding UTF8
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$generateScript = Join-Path $repoRoot "scripts\generate-all-seed-jobs.ps1"
$startBrowserScript = Join-Path $repoRoot "scripts\start-taobao-cdp-browser.ps1"
$watchdogScript = Join-Path $repoRoot "scripts\taobao-login-watchdog.ps1"
$exportScript = Join-Path $repoRoot "scripts\export-taobao-cookie-snapshot.ps1"
$localEnv = Join-Path $repoRoot "docker.local.env"

foreach ($required in @($generateScript, $startBrowserScript, $watchdogScript, $exportScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing required continuous collection helper: $required"
    }
}

foreach ($name in @("output", "datas", "jobs", "secrets")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot $name) | Out-Null
}

Ensure-EnvLine -Path $localEnv -Key "FAPAI_DATA_ROOT_HOST" -Value $DataRoot
Ensure-EnvLine -Path $localEnv -Key "FAPAI_SEED_JOBS_FILE" -Value "/data/jobs/seed_jobs_all.json"
Ensure-EnvLine -Path $localEnv -Key "FAPAI_COOKIE_SNAPSHOT" -Value "/data/secrets/taobao-cookies.json"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_PAGES_PER_RUN" -Value "20"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_LOOP_INTERVAL_SECONDS" -Value "60"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_PARALLEL_SORTS" -Value "1"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_TARGET_SUCCESS" -Value "10"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_MAX_ATTEMPTS" -Value "30"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_LOOP_INTERVAL_SECONDS" -Value "30"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS" -Value "0"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ANALYSIS_TARGET_SUCCESS" -Value "10"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ANALYSIS_MAX_ATTEMPTS" -Value "20"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS" -Value "30"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ANALYSIS_ACTIVE_LOOP_INTERVAL_SECONDS" -Value "0"
Ensure-EnvLine -Path $localEnv -Key "FAPAI_SEED_RESCAN_INTERVAL_SECONDS" -Value "900"
Ensure-EnvLine -Path $localEnv -Key "FAPAI_SEED_FAILURE_COOLDOWN_THRESHOLD" -Value "3"
Ensure-EnvLine -Path $localEnv -Key "FAPAI_SEED_FAILURE_COOLDOWN_SECONDS" -Value "1800"
Ensure-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_FAILURE_COOLDOWN_THRESHOLD" -Value "3"
Ensure-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_FAILURE_COOLDOWN_SECONDS" -Value "1800"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_COLLECTOR_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_COLLECTOR_2_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_COLLECTOR_3_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_COLLECTOR_4_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_COLLECTOR_5_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_COLLECTOR_6_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_WORKER_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_WORKER_2_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_WORKER_3_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ANALYSIS_WORKER_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ANALYSIS_WORKER_2_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ANALYSIS_WORKER_3_RESTART" -Value "unless-stopped"

& powershell -NoProfile -ExecutionPolicy Bypass -File $generateScript `
    -DataRoot $DataRoot `
    -Python $Python
if ($LASTEXITCODE -ne 0) {
    throw "Full seed job generation failed with exit code $LASTEXITCODE."
}

$startBrowserArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", $startBrowserScript,
    "-DataRoot", $DataRoot,
    "-Port", $Port
)
if ($UseSystemProxy) {
    $startBrowserArgs += "-UseSystemProxy"
}
& powershell @startBrowserArgs
if ($LASTEXITCODE -ne 0) {
    throw "Taobao CDP browser startup failed with exit code $LASTEXITCODE."
}

if (-not $SkipLoginWatchdog) {
    $watchdogArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $watchdogScript,
        "-DataRoot", $DataRoot,
        "-Port", $Port,
        "-Python", $Python
    )
    if ($UseSystemProxy) {
        $watchdogArgs += "-UseSystemProxy"
    }
    $watchdogArgs += "-SampleUrl"
    $watchdogArgs += $SampleUrl
    & powershell @watchdogArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Taobao login watchdog did not reach healthy state. Complete official verification and rerun."
    }
}
else {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $exportScript `
        -DataRoot $DataRoot `
        -Port $Port `
        -Python $Python `
        -SkipBrowserStart
}

if (-not $SkipDockerStart) {
    Write-Output "Starting collection workers with docker compose."
    $composeArgs = @(
        "compose",
        "--env-file", "docker.local.env",
        "-f", "docker-compose.collection.yml",
        "-f", "docker-compose.collection.host-bind.yml",
        "--profile", "api",
        "--profile", "analysis",
        "up", "-d"
    )
    if ($Build) {
        $composeArgs += "--build"
    }
    $composeArgs += @(
        "crow-api",
        "fapaifang-seed-collector",
        "fapaifang-seed-collector-2",
        "fapaifang-seed-collector-3",
        "fapaifang-seed-collector-4",
        "fapaifang-seed-collector-5",
        "fapaifang-seed-collector-6",
        "fapaifang-detail-worker",
        "fapaifang-detail-worker-2",
        "fapaifang-detail-worker-3",
        "fapaifang-detail-analysis-worker",
        "fapaifang-detail-analysis-worker-2",
        "fapaifang-detail-analysis-worker-3"
    )

    Push-Location $repoRoot
    try {
        & docker @composeArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Docker collection workers failed to start with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

Write-Output "Continuous FapaiFang collection is configured."
Write-Output "FAPAI_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json"
Write-Output "FAPAI_COOKIE_SNAPSHOT=/data/secrets/taobao-cookies.json"
Write-Output "FAPAI_SEED_PAGES_PER_RUN=20"
Write-Output "FAPAI_SEED_LOOP_INTERVAL_SECONDS=60"
Write-Output "FAPAI_SEED_PARALLEL_SORTS=1"
Write-Output "FAPAI_DETAIL_TARGET_SUCCESS=10"
Write-Output "FAPAI_DETAIL_MAX_ATTEMPTS=30"
Write-Output "FAPAI_DETAIL_LOOP_INTERVAL_SECONDS=30"
Write-Output "FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS=0"
Write-Output "FAPAI_DETAIL_ANALYSIS_TARGET_SUCCESS=10"
Write-Output "FAPAI_DETAIL_ANALYSIS_MAX_ATTEMPTS=20"
Write-Output "FAPAI_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS=30"
Write-Output "FAPAI_DETAIL_ANALYSIS_ACTIVE_LOOP_INTERVAL_SECONDS=0"
Write-Output "FAPAI_SEED_RESCAN_INTERVAL_SECONDS=900"
Write-Output "FAPAI_SEED_FAILURE_COOLDOWN_THRESHOLD=3"
Write-Output "FAPAI_SEED_FAILURE_COOLDOWN_SECONDS=1800"
Write-Output "FAPAI_DETAIL_FAILURE_COOLDOWN_THRESHOLD=3"
Write-Output "FAPAI_DETAIL_FAILURE_COOLDOWN_SECONDS=1800"
Write-Output "FAPAI_DETAIL_ANALYSIS_WORKER_RESTART=unless-stopped"
Write-Output "FAPAI_DETAIL_ANALYSIS_WORKER_2_RESTART=unless-stopped"
Write-Output "FAPAI_DETAIL_ANALYSIS_WORKER_3_RESTART=unless-stopped"
