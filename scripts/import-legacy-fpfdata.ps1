[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[A-Za-z0-9._-]+$")]
    [string]$SourceId,

    [string]$DestinationRoot = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
if (-not $DestinationRoot) {
    $DestinationRoot = Join-Path (Resolve-CrowProjectDataRoot -RepoRoot $repoRoot) ("imports\{0}" -f $SourceId)
}

$resolvedSource = (Resolve-Path -LiteralPath $SourceRoot).ProviderPath
$resolvedDestination = [System.IO.Path]::GetFullPath($DestinationRoot)
$sourcePrefix = $resolvedSource.TrimEnd("\") + "\"
$destinationPrefix = $resolvedDestination.TrimEnd("\") + "\"
if ($resolvedSource -eq $resolvedDestination -or
    $sourcePrefix.StartsWith($destinationPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
    $destinationPrefix.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Source and destination must be independent directory trees."
}

$includedPaths = @(
    "backups",
    "datas",
    "jobs",
    "output",
    "postgres\backups"
)
$excludedDirectoryNames = @(
    "analysis-env",
    "logs",
    "runtime",
    "secrets"
)
$excludedFilePatterns = @(
    ".env",
    ".env.*",
    "*.env",
    "*.env.*",
    "*cookie*",
    "*credential*",
    "*token*",
    "auth.json",
    "docker.local.env*"
)
$copiedPaths = @()

foreach ($relativePath in $includedPaths) {
    $sourcePath = Join-Path $resolvedSource $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
        continue
    }

    $destinationPath = Join-Path $resolvedDestination $relativePath
    if (-not $PSCmdlet.ShouldProcess($destinationPath, "Import $sourcePath")) {
        continue
    }

    New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null
    $robocopyArguments = @(
        $sourcePath,
        $destinationPath,
        "/E",
        "/COPY:DAT",
        "/DCOPY:DAT",
        "/FFT",
        "/XJ",
        "/R:2",
        "/W:2",
        "/NP",
        "/NFL",
        "/NDL",
        "/XD"
    ) + $excludedDirectoryNames + @("/XF") + $excludedFilePatterns
    & robocopy.exe @robocopyArguments
    $robocopyExitCode = $LASTEXITCODE
    if ($robocopyExitCode -ge 8) {
        throw "Robocopy failed for '$relativePath' with exit code $robocopyExitCode."
    }
    $copiedPaths += $relativePath
}

if ($copiedPaths.Count -gt 0) {
    $receipt = [ordered]@{
        schema_version = 1
        source_id = $SourceId
        source_root = $resolvedSource
        destination_root = $resolvedDestination
        imported_at_utc = [DateTime]::UtcNow.ToString("o")
        included_paths = $copiedPaths
        excluded_categories = @(
            "secrets",
            "runtime",
            "browser_profiles",
            "logs",
            "live_postgres_data",
            "secret_bearing_files"
        )
    }
    New-Item -ItemType Directory -Force -Path $resolvedDestination | Out-Null
    $receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $resolvedDestination "import-receipt.json") -Encoding UTF8
}

Write-Host ("Imported {0} archive path(s) into {1}" -f $copiedPaths.Count, $resolvedDestination)
