param(
    [int]$Port = 9225,
    [string]$DataRoot = "",
    [string]$OutputPath = "",
    [string]$Python = "",
    [switch]$AllowListOnly,
    [string]$TargetId = "",
    [switch]$NoThrowOnPending
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")
$DataRoot = Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$pythonResolver = Join-Path $PSScriptRoot "resolve-pc1-auth-python.ps1"
if (-not (Test-Path -LiteralPath $pythonResolver -PathType Leaf)) {
    throw "Missing PC1 auth Python resolver."
}
. $pythonResolver
$Python = Resolve-Pc1AuthPython -Requested $Python
$helper = Join-Path $repoRoot "tools\taobao_inplace_auth_handoff.py"
if (-not (Test-Path -LiteralPath $helper)) {
    throw "Missing in-place Taobao authentication helper."
}
if (-not $OutputPath) {
    $OutputPath = if ($env:FAPAI_COOKIE_SNAPSHOT) {
        $env:FAPAI_COOKIE_SNAPSHOT
    }
    else {
        Join-Path $DataRoot "secrets\nodes\pc2\taobao-cookies.json"
    }
}

$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ($previousPythonPath) { "$repoRoot;$previousPythonPath" } else { $repoRoot }
try {
    $arguments = @($helper, "--cdp-endpoint", "http://127.0.0.1:$Port", "--output-path", $OutputPath)
    if ($AllowListOnly) { $arguments += "--allow-list-only" }
    if ($TargetId) { $arguments += @("--required-target-id", $TargetId) }
    & $Python @arguments
    if ($LASTEXITCODE -ne 0) {
        if ($NoThrowOnPending) { exit $LASTEXITCODE }
        throw "PC1 in-place Taobao authentication is not reusable yet; collection remains paused."
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
