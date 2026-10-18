"""Run PowerShell presentation guards without touching a browser or scheduler."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not shutil.which("powershell.exe"), reason="Windows PowerShell required"
)


def run(script):
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    ).stdout


@pytest.mark.parametrize(
    "value,expected", [("$true", True), ("$false", False), ("$null", False)]
)
def test_public_demand_is_fail_closed(value, expected):
    helper = str(ROOT / "scripts/automatic-auth-demand.ps1").replace("'", "''")
    script = f"""
. '{helper}'
function ConvertTo-CollectionApiOrigin {{ return 'https://example.invalid' }}
function Invoke-RestMethod {{ return @{{auth_recovery=@{{automatic_auth_allowed={value}}}}} }}
Test-CrowAutomaticAuthDemand -ApiBase 'https://example.invalid' | ConvertTo-Json
"""
    assert json.loads(run(script)) is expected


def test_public_demand_unreachable_is_silent():
    helper = str(ROOT / "scripts/automatic-auth-demand.ps1").replace("'", "''")
    assert (
        json.loads(
            run(f"""
. '{helper}'
function ConvertTo-CollectionApiOrigin {{ return 'https://example.invalid' }}
function Invoke-RestMethod {{ throw 'offline' }}
Test-CrowAutomaticAuthDemand -ApiBase 'https://example.invalid' | ConvertTo-Json
""")
        )
        is False
    )


@pytest.mark.parametrize(
    "prefix",
    [
        "if ($null -eq $authTab -and -not $withinWindow)",
        "if ($null -ne $authTab -and (Test-Pc1RecoveryPromptDue",
        "if ($probeResult.blocking_scope -eq 'seed')",
    ],
)
def test_expired_demand_prevents_every_watcher_presentation(prefix):
    watcher = str(ROOT / "scripts/watch-pc1-nas-auth-recovery.ps1").replace("'", "''")
    output = run(
        r"""
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile('__WATCHER__',[ref]$null,[ref]$null)
$branch=$ast.Find({param($n) $n -is [Management.Automation.Language.IfStatementAst] -and $n.Extent.Text.StartsWith('__PREFIX__')},$true)
if (-not $branch) { throw 'Missing branch' }
function Test-CurrentAutomaticRecovery { return $false }
function Test-Pc1RecoveryPromptDue { return $true }
function Show-Pc1RecoveryPrompt { Write-Output 'FORBIDDEN' }
function Show-Pc1RecoverySeedPrompt { Write-Output 'FORBIDDEN' }
$authTab=if ('__PREFIX__'.StartsWith('if ($null -eq')) {$null} else {@{id='existing'}}
$withinWindow=$false
$probeResult=@{blocking_scope='seed'}
$newState=@{prompted_at=''}
. ([scriptblock]::Create($branch.Extent.Text))
throw 'Presentation guard did not exit'
""".replace("__WATCHER__", watcher).replace("__PREFIX__", prefix.replace("'", "''"))
    )
    assert "FORBIDDEN" not in output
