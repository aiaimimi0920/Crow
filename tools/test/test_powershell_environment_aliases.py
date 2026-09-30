"""Run only the pure environment helper, never an operational PowerShell script."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_powershell_alias_reader_and_explicit_writer_preserve_scope(tmp_path):
    shell = (
        os.environ.get("CROW_TEST_POWERSHELL")
        or shutil.which("pwsh")
        or shutil.which("powershell")
    )
    if not shell:
        pytest.skip("PowerShell is unavailable")
    helper = str(ROOT / "scripts/project-environment.ps1").replace("'", "''")
    script = tmp_path / "aliases.ps1"
    script.write_text(
        ". '"
        + helper
        + "'\n"
        + r"""
$ErrorActionPreference = 'Stop'
$env:CROW_TEST_VALUE = 'global-conflict-new'
$env:FAPAI_TEST_VALUE = 'global-conflict-old'
$fixture = [ordered]@{FAPAI_TEST_VALUE = 'old'}
$results = @()
$results += Get-CrowEnvironmentValue -Name CROW_TEST_VALUE -Environment $fixture
$fixture.FAPAI_TEST_VALUE = 'changed'
$results += Get-CrowEnvironmentValue -Name CROW_TEST_VALUE -Environment $fixture
$fixture.CROW_TEST_VALUE = 'changed'
$results += Get-CrowEnvironmentValue -Name FAPAI_TEST_VALUE -Environment $fixture
$results += Get-CrowEnvironmentValue -Name CROW_TEST_ABSENT -Default 'fallback' -Environment $fixture
$fixture.CROW_TEST_VALUE = ''
$fixture.FAPAI_TEST_VALUE = ''
$results += (Get-CrowEnvironmentValue -Name CROW_TEST_VALUE -Default 'wrong' -Environment $fixture) -eq ''
$fixture.CROW_TEST_VALUE = 'private-new'
$fixture.FAPAI_TEST_VALUE = 'private-old'
try { Get-CrowEnvironmentValue -Name CROW_TEST_VALUE -Environment $fixture; throw 'missing conflict' }
catch { $results += $_.Exception.Message }
Set-CrowEnvironmentValue -Name CROW_TEST_VALUE -Value 'written' -Environment $fixture
$results += $fixture.CROW_TEST_VALUE
$results += $fixture.FAPAI_TEST_VALUE
$results += $env:CROW_TEST_VALUE
$results += Get-CrowEnvironmentValue -Name OTHER_KEY -Default 'external-default' -Environment $fixture
$results | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-File", str(script)],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout)
    assert values == [
        "old",
        "changed",
        "changed",
        "fallback",
        True,
        "Conflicting environment aliases: CROW_TEST_VALUE, FAPAI_TEST_VALUE",
        "written",
        "written",
        "global-conflict-new",
        "external-default",
    ]


def test_real_parameter_blocks_keep_explicit_override_and_alias_conflicts(tmp_path):
    shell = (
        os.environ.get("CROW_TEST_POWERSHELL")
        or shutil.which("pwsh")
        or shutil.which("powershell")
    )
    if not shell:
        pytest.skip("PowerShell is unavailable")
    root = str(ROOT).replace("'", "''")
    script = tmp_path / "parameter-binding.ps1"
    script.write_text(
        "$repo = '"
        + root
        + "'\n"
        + r"""
$ErrorActionPreference = 'Stop'
. (Join-Path $repo 'scripts/project-environment.ps1')
$cases = @(
    @('backup-postgres-to-host.ps1', 'PostgresPassword', 'POSTGRES_PASSWORD'),
    @('sync-docker-data-to-host.ps1', 'PostgresPassword', 'POSTGRES_PASSWORD'),
    @('deploy-collector-desktop-local.ps1', 'ApiBase', 'COLLECTOR_API_BASE'),
    @('write-collector-desktop-runtime-config.ps1', 'ApiBase', 'COLLECTOR_API_BASE')
)
$results = @()
foreach ($case in $cases) {
    $tokens=$null; $errors=$null
    $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $repo ('scripts/' + $case[0])), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw 'source parse failure' }
    $defaults = @($ast.EndBlock.Statements | Where-Object { $_.Extent.Text.StartsWith('if (-not $PSBoundParameters.ContainsKey(') })
    if ($defaults.Count -ne 1) { throw 'unexpected default binding boundary' }
    $body = $ast.ParamBlock.Extent.Text + "`n" + $defaults[0].Extent.Text + "`n" + ('$' + $case[1])
    $fixture = [scriptblock]::Create($body)
    $parameters = @{}
    if ($case[0] -eq 'write-collector-desktop-runtime-config.ps1') { $parameters.InstallRoot = $repo; $parameters.DataRoot = $repo }
    Remove-Item -LiteralPath ('Env:CROW_' + $case[2]) -ErrorAction SilentlyContinue
    [Environment]::SetEnvironmentVariable(('FAPAI_' + $case[2]), 'legacy-fixture', 'Process')
    $results += & $fixture @parameters
    [Environment]::SetEnvironmentVariable(('CROW_' + $case[2]), 'canonical-fixture', 'Process')
    Remove-Item -LiteralPath ('Env:FAPAI_' + $case[2]) -ErrorAction SilentlyContinue
    $results += & $fixture @parameters
    [Environment]::SetEnvironmentVariable(('FAPAI_' + $case[2]), 'private-conflict', 'Process')
    $parameters[$case[1]] = 'explicit-fixture'
    $results += & $fixture @parameters
    $parameters.Remove($case[1])
    try { $null = & $fixture @parameters; $results += 'missing conflict' }
    catch { $results += $_.Exception.Message.StartsWith('Conflicting environment aliases:') }
}
$path = Join-Path $repo 'not-created-profile'
$values = @{CROW_TEST_PATH=$path; FAPAI_TEST_PATH=($path + [IO.Path]::DirectorySeparatorChar)}
$results += (Get-CrowEnvironmentValue -Name CROW_TEST_PATH -Environment $values -PathValue) -eq $path

if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
    $rootAliases = @{CROW_TEST_PATH='C:\'; FAPAI_TEST_PATH='C:/'}
    $results += (Get-CrowEnvironmentValue CROW_TEST_PATH -Environment $rootAliases -PathValue) -eq 'C:\'
    $uncAliases = @{CROW_TEST_PATH='\\server\share\'; FAPAI_TEST_PATH='\\SERVER\SHARE'}
    $results += (Get-CrowEnvironmentValue CROW_TEST_PATH -Environment $uncAliases -PathValue) -eq '\\server\share\'
    $driveRelative = @{CROW_TEST_PATH='C:\'; FAPAI_TEST_PATH='C:'}
    $previousDirectory = [Environment]::CurrentDirectory
    try { [Environment]::CurrentDirectory = 'C:\'; $null = Get-CrowEnvironmentValue CROW_TEST_PATH -Environment $driveRelative -PathValue; $results += $false }
    catch { $results += $true }
    finally { [Environment]::CurrentDirectory = $previousDirectory }
} else {
    $rootAliases = @{CROW_TEST_PATH='/'; FAPAI_TEST_PATH='//'}
    $results += (Get-CrowEnvironmentValue CROW_TEST_PATH -Environment $rootAliases -PathValue) -eq '/'
    $literalSlash = @{CROW_TEST_PATH=($path + '\'); FAPAI_TEST_PATH=$path}
    try { $null = Get-CrowEnvironmentValue CROW_TEST_PATH -Environment $literalSlash -PathValue; $results += $false }
    catch { $results += $true }
    $results += $true
}
$results | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-File", str(script)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        "legacy-fixture",
        "canonical-fixture",
        "explicit-fixture",
        True,
    ] * 4 + [True, True, True, True]
    assert not (ROOT / "not-created-profile").exists()
