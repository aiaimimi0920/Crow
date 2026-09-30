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
