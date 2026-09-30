param(
    [string]$DataRoot = "",
    [int]$Port = 9223,
    [string]$Python = "python",
    [int]$DetailTargetSuccess = 10,
    [int]$AnalysisTargetSuccess = 10,
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
$DataRoot = Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot

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
$startBrowserScript = Join-Path $repoRoot "scripts\start-taobao-cdp-browser.ps1"
$watchdogScript = Join-Path $repoRoot "scripts\taobao-login-watchdog.ps1"
$exportScript = Join-Path $repoRoot "scripts\export-taobao-cookie-snapshot.ps1"
$localEnv = Join-Path $repoRoot "docker.local.env"

foreach ($required in @($startBrowserScript, $watchdogScript, $exportScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing required detail analysis helper: $required"
    }
}

foreach ($name in @("output", "datas", "jobs", "secrets")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot $name) | Out-Null
}

Set-EnvLine -Path $localEnv -Key "FAPAI_DATA_ROOT_HOST" -Value $DataRoot
Set-EnvLine -Path $localEnv -Key "FAPAI_COOKIE_SNAPSHOT" -Value "/data/secrets/taobao-cookies.json"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_COLLECTOR_RESTART" -Value "no"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_COLLECTOR_2_RESTART" -Value "no"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_COLLECTOR_3_RESTART" -Value "no"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_COLLECTOR_4_RESTART" -Value "no"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_COLLECTOR_5_RESTART" -Value "no"
Set-EnvLine -Path $localEnv -Key "FAPAI_SEED_COLLECTOR_6_RESTART" -Value "no"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_WORKER_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_WORKER_2_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_WORKER_3_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ANALYSIS_WORKER_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ANALYSIS_WORKER_2_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ANALYSIS_WORKER_3_RESTART" -Value "unless-stopped"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_TARGET_SUCCESS" -Value ([string]$DetailTargetSuccess)
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_LOOP_INTERVAL_SECONDS" -Value "30"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ANALYSIS_TARGET_SUCCESS" -Value ([string]$AnalysisTargetSuccess)
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS" -Value "30"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_FAILURE_COOLDOWN_THRESHOLD" -Value "3"
Set-EnvLine -Path $localEnv -Key "FAPAI_DETAIL_FAILURE_COOLDOWN_SECONDS" -Value "1800"

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
    Disable-DockerRestartPolicy -Services $seedServices
    Write-Output "Stopping seed workers before detail-only analysis."
    & docker compose --env-file docker.local.env -f docker-compose.collection.yml -f docker-compose.collection.host-bind.yml stop @seedServices
    if ($LASTEXITCODE -ne 0) {
        throw "Docker compose failed to stop seed workers with exit code $LASTEXITCODE."
    }

    Write-Output "Starting detail-only analysis workers with docker compose."
    $composeArgs = @(
        "compose",
        "--env-file", "docker.local.env",
        "-f", "docker-compose.collection.yml",
        "-f", "docker-compose.collection.host-bind.yml",
        "--profile", "analysis",
        "up", "-d"
    )
    if ($Build) {
        $composeArgs += "--build"
    }
    $composeArgs += $detailServices

    & docker @composeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Docker detail-only workers failed to start with exit code $LASTEXITCODE."
    }

    Disable-DockerRestartPolicy -Services $seedServices
    Write-Output "Re-confirming seed workers are stopped after detail-only startup."
    & docker compose --env-file docker.local.env -f docker-compose.collection.yml -f docker-compose.collection.host-bind.yml stop @seedServices
    if ($LASTEXITCODE -ne 0) {
        throw "Docker compose failed to re-stop seed workers with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

Write-Output "Detail-only analysis mode is configured."
Write-Output "FAPAI_COOKIE_SNAPSHOT=/data/secrets/taobao-cookies.json"
Write-Output "FAPAI_SEED_COLLECTOR_RESTART=no"
Write-Output "FAPAI_SEED_COLLECTOR_2_RESTART=no"
Write-Output "FAPAI_SEED_COLLECTOR_3_RESTART=no"
Write-Output "FAPAI_SEED_COLLECTOR_4_RESTART=no"
Write-Output "FAPAI_SEED_COLLECTOR_5_RESTART=no"
Write-Output "FAPAI_SEED_COLLECTOR_6_RESTART=no"
Write-Output "FAPAI_DETAIL_TARGET_SUCCESS=$DetailTargetSuccess"
Write-Output "FAPAI_DETAIL_LOOP_INTERVAL_SECONDS=30"
Write-Output "FAPAI_DETAIL_ANALYSIS_WORKER_RESTART=unless-stopped"
Write-Output "FAPAI_DETAIL_ANALYSIS_WORKER_2_RESTART=unless-stopped"
Write-Output "FAPAI_DETAIL_ANALYSIS_WORKER_3_RESTART=unless-stopped"
Write-Output "FAPAI_DETAIL_ANALYSIS_TARGET_SUCCESS=$AnalysisTargetSuccess"
Write-Output "FAPAI_DETAIL_ANALYSIS_LOOP_INTERVAL_SECONDS=30"
Write-Output "FAPAI_DETAIL_FAILURE_COOLDOWN_THRESHOLD=3"
Write-Output "FAPAI_DETAIL_FAILURE_COOLDOWN_SECONDS=1800"
