# Load the same source helpers in a checkout or a flat operator bundle.
$crowEnvironmentCandidates = @(
    (Join-Path $PSScriptRoot 'runtime'),
    (Join-Path $PSScriptRoot '..\..\scripts')
)
$crowEnvironmentRoot = $null
foreach ($candidate in $crowEnvironmentCandidates) {
    if ((Test-Path -LiteralPath (Join-Path $candidate 'project-environment.ps1') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $candidate 'compose-environment-file.ps1') -PathType Leaf)) {
        $crowEnvironmentRoot = $candidate
        break
    }
}
if (-not $crowEnvironmentRoot) { throw 'Crow operator environment helpers are missing from the bundle' }
. (Join-Path $crowEnvironmentRoot 'project-environment.ps1')
. (Join-Path $crowEnvironmentRoot 'compose-environment-file.ps1')

function Read-CrowOperatorEnvironment {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return @{} }
    $values = @{}
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        $text = $line.Trim()
        if (-not $text -or $text.StartsWith('#')) { continue }
        $separator = $text.IndexOf('=')
        if ($separator -lt 1) { continue }
        $name = $text.Substring(0, $separator).Trim()
        if ($name -match '^(CROW|FAPAI)_[A-Za-z0-9_]+$') { $name = $name.ToUpperInvariant() }
        $values[$name] = $text.Substring($separator + 1)
    }
    return $values
}

function Import-CrowOperatorEnvironment {
    param([Parameter(Mandatory = $true)][string]$Path)
    $values = Read-CrowOperatorEnvironment -Path $Path
    $prepared = @{}
    foreach ($name in $values.Keys) {
        $isPath = $name -match '^(?:CROW|FAPAI)_.+(?:_ROOT|_ROOT_HOST|_PATH|_FILE|_DIR|_SNAPSHOT)$'
        $value = Get-CrowEnvironmentValue -Name $name -Environment $values -PathValue:$isPath
        Set-CrowEnvironmentValue -Name $name -Value $value -Environment $prepared
    }
    # Validate the complete file before replacing any process alias group.
    foreach ($name in $prepared.Keys) {
        [Environment]::SetEnvironmentVariable($name, $prepared[$name], 'Process')
    }
}
