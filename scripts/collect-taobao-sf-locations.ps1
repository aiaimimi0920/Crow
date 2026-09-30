param(
    [ValidateSet("crawl", "report", "merge-overrides")]
    [string]$Mode = "crawl",
    [string]$DataRoot = "",
    [string]$AllLocationsFile = "",
    [string]$ObservedPath = "",
    [string]$ReportPath = "",
    [string]$ExistingOverridesPath = "",
    [string]$OutputOverridesPath = "",
    [string]$CdpEndpoint = "http://127.0.0.1:9223",
    [string]$Province = "",
    [int]$MaxProvinces = 0,
    [int]$MaxCitiesPerProvince = 0,
    [double]$DelaySeconds = 8.0,
    [int]$WaitMs = 1500,
    [string]$Category = "50025969",
    [string]$Python = "python",
    [switch]$NoResume
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")

function Resolve-FapaiDataRoot {
    return Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$tool = Join-Path $repoRoot "tools\taobao_sf_locations.py"
if (-not (Test-Path -LiteralPath $tool)) {
    throw "Missing Taobao SF location tool: $tool"
}

$dataRootResolved = Resolve-FapaiDataRoot
$dataDatas = Join-Path $dataRootResolved "datas"
New-Item -ItemType Directory -Force -Path $dataDatas | Out-Null

if (-not $AllLocationsFile) {
    $AllLocationsFile = Join-Path $repoRoot "datas\all_locations.json"
}
if (-not $ObservedPath) {
    $ObservedPath = Join-Path $dataDatas "taobao_sf_locations_observed.json"
}
if (-not $ReportPath) {
    $ReportPath = Join-Path $dataDatas "taobao_sf_locations_report.json"
}
if (-not $ExistingOverridesPath) {
    $ExistingOverridesPath = Join-Path $repoRoot "datas\taobao_sf_location_overrides.json"
}
if (-not $OutputOverridesPath) {
    $OutputOverridesPath = Join-Path $repoRoot "datas\taobao_sf_location_overrides.json"
}

if (-not (Test-Path -LiteralPath $AllLocationsFile)) {
    throw "Missing all locations file: $AllLocationsFile"
}

$previousPythonPath = $env:PYTHONPATH
if ($previousPythonPath) {
    $env:PYTHONPATH = "$repoRoot;$previousPythonPath"
}
else {
    $env:PYTHONPATH = $repoRoot
}

$argsList = @($tool, $Mode)
if ($Mode -eq "crawl") {
    $argsList += @(
        "--cdp-endpoint", $CdpEndpoint,
        "--all-locations-file", $AllLocationsFile,
        "--output", $ObservedPath,
        "--category", $Category,
        "--delay-seconds", $DelaySeconds,
        "--wait-ms", $WaitMs
    )
    if ($Province) {
        $argsList += @("--province", $Province)
    }
    if ($MaxProvinces -gt 0) {
        $argsList += @("--max-provinces", $MaxProvinces)
    }
    if ($MaxCitiesPerProvince -gt 0) {
        $argsList += @("--max-cities-per-province", $MaxCitiesPerProvince)
    }
    if ($NoResume) {
        $argsList += "--no-resume"
    }
}
elseif ($Mode -eq "report") {
    $argsList += @(
        "--all-locations-file", $AllLocationsFile,
        "--observed", $ObservedPath,
        "--output", $ReportPath
    )
}
elseif ($Mode -eq "merge-overrides") {
    $argsList += @(
        "--observed", $ObservedPath,
        "--existing", $ExistingOverridesPath,
        "--output", $OutputOverridesPath
    )
}

try {
    & $Python @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "Taobao SF location $Mode failed with exit code $LASTEXITCODE."
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}

if ($Mode -eq "crawl") {
    Write-Output "Observed Taobao SF locations: $ObservedPath"
}
elseif ($Mode -eq "report") {
    Write-Output "Taobao SF location report: $ReportPath"
}
elseif ($Mode -eq "merge-overrides") {
    Write-Output "Updated Taobao SF overrides: $OutputOverridesPath"
}
