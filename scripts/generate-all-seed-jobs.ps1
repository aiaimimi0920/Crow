param(
    [string]$DataRoot = "",
    [string]$LocationsFile = "",
    [string]$TaobaoLocationsFile = "",
    [string]$OutputPath = "",
    [string]$Python = "python",
    [string[]]$Categories = @("50025969", "200782003"),
    [int]$MaxPage = 83
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")

function Resolve-FapaiDataRoot {
    return Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$generator = Join-Path $repoRoot "tools\generate_seed_jobs.py"
if (-not (Test-Path -LiteralPath $generator)) {
    throw "Missing seed job generator: $generator"
}

$previousPythonPath = $env:PYTHONPATH
if ($previousPythonPath) {
    $env:PYTHONPATH = "$repoRoot;$previousPythonPath"
}
else {
    $env:PYTHONPATH = $repoRoot
}

$dataRootResolved = Resolve-FapaiDataRoot
if (-not $LocationsFile) {
    $LocationsFile = Join-Path $repoRoot "datas\all_locations.json"
}
if (-not $TaobaoLocationsFile) {
    $defaultTaobaoLocationsFile = Join-Path $repoRoot "datas\taobao_sf_location_overrides.json"
    if (Test-Path -LiteralPath $defaultTaobaoLocationsFile) {
        $TaobaoLocationsFile = $defaultTaobaoLocationsFile
    }
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $dataRootResolved "jobs\seed_jobs_all.json"
}

if (-not (Test-Path -LiteralPath $LocationsFile)) {
    throw "Missing locations file: $LocationsFile"
}

$outputParent = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outputParent | Out-Null

$argsList = @(
    $generator,
    "--locations-file", $LocationsFile,
    "--output", $OutputPath
)
if ($TaobaoLocationsFile) {
    if (-not (Test-Path -LiteralPath $TaobaoLocationsFile)) {
        throw "Missing Taobao SF locations file: $TaobaoLocationsFile"
    }
    $argsList += @("--taobao-locations-file", $TaobaoLocationsFile)
}
$argsList += @("--categories")
$argsList += $Categories
$argsList += @("--max-page", $MaxPage)

try {
    & $Python @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "Seed job generation failed with exit code $LASTEXITCODE."
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Output "Generated FapaiFang full seed jobs: $OutputPath"
Write-Output "Docker worker path: /data/jobs/seed_jobs_all.json"
Write-Output "Set FAPAI_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json"
