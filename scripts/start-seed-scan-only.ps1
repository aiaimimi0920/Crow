param(
    [string]$DataRoot = "",
    [int]$Port = 9223,
    [string]$Python = "python",
    [int]$SeedPagesPerRun = 20,
    [string[]]$SampleUrl = @(
        "https://sf.taobao.com/list/50025969__2.htm",
        "https://sf.taobao.com/list/200782003__1.htm"
    ),
    [switch]$UseSystemProxy,
    [switch]$SkipLoginWatchdog,
    [switch]$Build
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")
. (Join-Path $PSScriptRoot "compose-environment-file.ps1")
$DataRoot = Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot

function Set-EnvLine {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )
    Set-CrowEnvironmentFileValue -Path $Path -Key $Key -Value $Value
}

function Disable-DockerRestartPolicy {
    param([Parameter(Mandatory = $true)][string[]]$Services)

    $existing = @()
    foreach ($service in $Services) {
        $matches = & docker ps -a --filter "name=^/$service$" --format "{{.Names}}"
        if ($LASTEXITCODE -ne 0) {
            throw "Docker container lookup failed for $service with exit code $LASTEXITCODE."
        }
        $existing += @($matches | Where-Object { $_ })
    }
    if ($existing.Count -eq 0) {
        return
    }

    Write-Output "Running docker update --restart=no for paused worker pool."
    $updateArgs = @("update", "--restart=no") + $existing
    & docker @updateArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Docker restart policy update failed with exit code $LASTEXITCODE."
    }
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$composeWrapper = Join-Path $repoRoot "tools\crow_compose.py"
if (-not (Test-Path -LiteralPath $composeWrapper -PathType Leaf)) { throw "Crow Compose adapter is unavailable" }
$generateScript = Join-Path $repoRoot "scripts\generate-all-seed-jobs.ps1"
$startBrowserScript = Join-Path $repoRoot "scripts\start-taobao-cdp-browser.ps1"
$watchdogScript = Join-Path $repoRoot "scripts\taobao-login-watchdog.ps1"
$exportScript = Join-Path $repoRoot "scripts\export-taobao-cookie-snapshot.ps1"
$localEnv = Join-Path $repoRoot "docker.local.env"

foreach ($required in @($generateScript, $startBrowserScript, $watchdogScript, $exportScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing required seed scan helper: $required"
    }
}

foreach ($name in @("output", "datas", "jobs", "secrets")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot $name) | Out-Null
}

Set-EnvLine -Path $localEnv -Key "CROW_DATA_ROOT_HOST" -Value $DataRoot
Set-EnvLine -Path $localEnv -Key "CROW_SEED_JOBS_FILE" -Value "/data/jobs/seed_jobs_all.json"
Set-EnvLine -Path $localEnv -Key "CROW_COOKIE_SNAPSHOT" -Value "/data/secrets/taobao-cookies.json"
Set-EnvLine -Path $localEnv -Key "CROW_SEED_PAGES_PER_RUN" -Value ([string]$SeedPagesPerRun)
Set-EnvLine -Path $localEnv -Key "CROW_SEED_LOOP_INTERVAL_SECONDS" -Value "60"
Set-EnvLine -Path $localEnv -Key "CROW_SEED_PARALLEL_SORTS" -Value "1"
Set-EnvLine -Path $localEnv -Key "CROW_SEED_RESCAN_INTERVAL_SECONDS" -Value "900"
Set-EnvLine -Path $localEnv -Key "CROW_SEED_FAILURE_COOLDOWN_THRESHOLD" -Value "10"
Set-EnvLine -Path $localEnv -Key "CROW_SEED_FAILURE_COOLDOWN_SECONDS" -Value "120"
Set-EnvLine -Path $localEnv -Key "CROW_LIST_HTTP_TIMEOUT_SECONDS" -Value "8"
Set-EnvLine -Path $localEnv -Key "CROW_LIST_BROWSER_FALLBACK" -Value "0"
Set-EnvLine -Path $localEnv -Key "CROW_SEED_COLLECTOR_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "CROW_SEED_COLLECTOR_2_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "CROW_SEED_COLLECTOR_3_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "CROW_SEED_COLLECTOR_4_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "CROW_SEED_COLLECTOR_5_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "CROW_SEED_COLLECTOR_6_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "CROW_DETAIL_WORKER_RESTART" -Value "no"
Set-EnvLine -Path $localEnv -Key "CROW_DETAIL_WORKER_2_RESTART" -Value "no"
Set-EnvLine -Path $localEnv -Key "CROW_DETAIL_WORKER_3_RESTART" -Value "no"
Set-EnvLine -Path $localEnv -Key "CROW_DETAIL_ANALYSIS_WORKER_RESTART" -Value "no"
Set-EnvLine -Path $localEnv -Key "CROW_DETAIL_ANALYSIS_WORKER_2_RESTART" -Value "no"
Set-EnvLine -Path $localEnv -Key "CROW_DETAIL_ANALYSIS_WORKER_3_RESTART" -Value "no"

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
    if ($LASTEXITCODE -ne 0) {
        throw "Cookie snapshot export failed with exit code $LASTEXITCODE."
    }
}

$seedServices = @(
    "fapaifang-seed-collector",
    "fapaifang-seed-collector-2",
    "fapaifang-seed-collector-3",
    "fapaifang-seed-collector-4",
    "fapaifang-seed-collector-5",
    "fapaifang-seed-collector-6"
)
$detailServices = @(
    "fapaifang-detail-worker",
    "fapaifang-detail-worker-2",
    "fapaifang-detail-worker-3",
    "fapaifang-detail-analysis-worker",
    "fapaifang-detail-analysis-worker-2",
    "fapaifang-detail-analysis-worker-3"
)

Push-Location $repoRoot
try {
    & $Python $composeWrapper --check --data-root-host $DataRoot -- --env-file docker.local.env -f docker-compose.collection.yml -f docker-compose.collection.host-bind.yml config
    if ($LASTEXITCODE -ne 0) { throw "Crow Compose environment rejected before worker changes" }
    Disable-DockerRestartPolicy -Services $detailServices
    Write-Output "Stopping detail workers before seed-only scan."
    & $Python $composeWrapper --data-root-host $DataRoot -- --env-file docker.local.env -f docker-compose.collection.yml -f docker-compose.collection.host-bind.yml --profile analysis stop @detailServices
    if ($LASTEXITCODE -ne 0) {
        throw "Docker compose failed to stop detail workers with exit code $LASTEXITCODE."
    }

    Write-Output "Starting seed-only scan workers with docker compose."
    $composeArgs = @(
        "compose",
        "--env-file", "docker.local.env",
        "-f", "docker-compose.collection.yml",
        "-f", "docker-compose.collection.host-bind.yml",
        "up", "-d"
    )
    if ($Build) {
        $composeArgs += "--build"
    }
    $composeArgs += $seedServices

    $crowComposeArgs = @("--data-root-host", $DataRoot, "--") + @($composeArgs | Select-Object -Skip 1)
    & $Python $composeWrapper @crowComposeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Docker seed-only workers failed to start with exit code $LASTEXITCODE."
    }

    Disable-DockerRestartPolicy -Services $detailServices
    Write-Output "Re-confirming detail workers are stopped after seed-only startup."
    & $Python $composeWrapper --data-root-host $DataRoot -- --env-file docker.local.env -f docker-compose.collection.yml -f docker-compose.collection.host-bind.yml --profile analysis stop @detailServices
    if ($LASTEXITCODE -ne 0) {
        throw "Docker compose failed to re-stop detail workers with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

Write-Output "Seed-only scan mode is configured."
Write-Output "CROW_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json"
Write-Output "CROW_COOKIE_SNAPSHOT=/data/secrets/taobao-cookies.json"
Write-Output "CROW_SEED_PAGES_PER_RUN=$SeedPagesPerRun"
Write-Output "CROW_SEED_LOOP_INTERVAL_SECONDS=60"
Write-Output "CROW_SEED_PARALLEL_SORTS=1"
Write-Output "CROW_SEED_RESCAN_INTERVAL_SECONDS=900"
Write-Output "CROW_SEED_FAILURE_COOLDOWN_THRESHOLD=10"
Write-Output "CROW_SEED_FAILURE_COOLDOWN_SECONDS=120"
Write-Output "CROW_LIST_HTTP_TIMEOUT_SECONDS=8"
Write-Output "CROW_LIST_BROWSER_FALLBACK=0"
Write-Output "CROW_DETAIL_WORKER_RESTART=no"
Write-Output "CROW_DETAIL_WORKER_2_RESTART=no"
Write-Output "CROW_DETAIL_WORKER_3_RESTART=no"
Write-Output "CROW_DETAIL_ANALYSIS_WORKER_RESTART=no"
Write-Output "CROW_DETAIL_ANALYSIS_WORKER_2_RESTART=no"
Write-Output "CROW_DETAIL_ANALYSIS_WORKER_3_RESTART=no"
