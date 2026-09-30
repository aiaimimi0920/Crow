param(
    [ValidateSet("open", "complete", "status")][string]$Action,
    [string]$ApiBase,
    [string]$TargetUrl = "",
    [string]$TargetId = "",
    [string]$RequestId = "",
    [string]$ChallengeId = "",
    [string]$RecoveryId = "",
    [ValidateSet("", "seed", "detail")][string]$Scope = "",
    [string]$PeerUrl = "",
    [string]$PeerChallengeId = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$previous = @{
    PYTHONPATH = $env:PYTHONPATH
    PYTHONIOENCODING = $env:PYTHONIOENCODING
    PYTHONUTF8 = $env:PYTHONUTF8
}
$failure = "runtime_config_invalid"
$exitCode = 1
$locationPushed = $false

function Write-LaunchFailure {
    param([string]$Kind, [int]$Code)
    # Persist only bounded metadata, never stderr, URLs, cookies or credentials.
    try {
        $directory = Join-Path (Resolve-CrowProjectDataRoot -RepoRoot $root) "desktop-auth"
        [IO.Directory]::CreateDirectory($directory) | Out-Null
        $receipt = [ordered]@{
            version = 1
            failed_at = [DateTime]::UtcNow.ToString("o")
            action = $Action
            failure = $Kind
            exit_code = $Code
        } | ConvertTo-Json -Compress
        [IO.File]::WriteAllText((Join-Path $directory "last-launch-failure.json"), $receipt, (New-Object Text.UTF8Encoding($false)))
    } catch { } # A read-only bundle must not obscure the original launch failure.
}

try {
    $python = $env:FAPAI_DESKTOP_PYTHON_PATH
    $configPath = Join-Path $root "crow-desktop.runtime.json"
    if (Test-Path -LiteralPath $configPath) {
        if ((Get-Item -LiteralPath $configPath).Length -gt 16384) { throw "runtime_config_invalid" }
        $config = [IO.File]::ReadAllText($configPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
        if ($config.version -ne 1 -or $config.environment -isnot [pscustomobject]) { throw "runtime_config_invalid" }
        if (-not $python) { $python = $config.environment.FAPAI_DESKTOP_PYTHON_PATH }
    }
    $failure = "python_unavailable"
    if ($null -ne $python -and $python -ne "") {
        if ($python -isnot [string] -or $python -match '[\x00-\x1f]' -or
            -not [IO.Path]::IsPathRooted($python) -or
            [IO.Path]::GetFullPath($python) -ne $python -or
            -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "python_unavailable" }
    } else {
        # Legacy/development bundles only. Never silently replace a configured interpreter.
        $python = (Get-Command python -CommandType Application -ErrorAction Stop).Source
    }
    $failure = "helper_missing"
    if (-not (Test-Path -LiteralPath (Join-Path $root "tools\pc1_desktop_auth.py") -PathType Leaf)) { throw "helper_missing" }
    # -m searches the working directory before PYTHONPATH. Pin both to this bundle.
    Push-Location -LiteralPath $root
    $locationPushed = $true
    $env:PYTHONPATH = $root
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    $arguments = @("-m", "tools.pc1_desktop_auth", "--action", $Action, "--api-base", $ApiBase)
    foreach ($entry in @(@("--target-url", $TargetUrl), @("--target-id", $TargetId),
                        @("--request-id", $RequestId), @("--challenge-id", $ChallengeId), @("--recovery-id", $RecoveryId), @("--scope", $Scope),
                        @("--peer-url", $PeerUrl), @("--peer-challenge-id", $PeerChallengeId))) {
        if ($entry[1]) { $arguments += $entry }
    }
    $failure = "python_launch"
    # Native commands publish their exit code in the global scope. A script-local
    # copy stays $null when this file is dot-called (& script) instead of -File,
    # which would misreport a successful helper as python_launch.
    $global:LASTEXITCODE = $null
    # Windows PowerShell can turn native stderr warnings into NativeCommandError.
    # The child's exit code, not the presence of stderr, determines failure.
    $ErrorActionPreference = "Continue"
    try { & $python @arguments }
    finally { $ErrorActionPreference = "Stop" }
    if ($null -ne $global:LASTEXITCODE) {
        $exitCode = $global:LASTEXITCODE
        $failure = "python_exit"
    }
}
catch { $exitCode = 1 }
finally {
    if ($locationPushed) { Pop-Location }
    foreach ($key in $previous.Keys) { [Environment]::SetEnvironmentVariable($key, $previous[$key], "Process") }
}
if ($exitCode -ne 0) { Write-LaunchFailure -Kind $failure -Code $exitCode }
exit $exitCode
