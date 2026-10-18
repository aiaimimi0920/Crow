"""Exercise real PowerShell policy without opening a browser or reading cookies."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not shutil.which("powershell.exe"), reason="Windows PowerShell required"
)
@pytest.mark.parametrize("same_target", [False, True])
def test_seed_prompt_is_deferred_then_deduplicated(same_target):
    policy = (
        Path(__file__).resolve().parents[2] / "scripts/pc1-auth-recovery-policy.ps1"
    )
    script = r"""
$ErrorActionPreference = 'Stop'
. '__POLICY__'
$script:shows = 0
$script:reads = 0
$script:saved = $null
function Write-State { param($Path,$State); $script:saved = $State | ConvertTo-Json | ConvertFrom-Json }
function Get-CdpTabs { $script:reads++; return @(@{id='seed';type='page';url='https://sf.taobao.com/list/50025969__2.htm'}) }
function Invoke-CdpWebRequest { throw 'No tab creation expected' }
function Show-Pc1RecoveryPrompt { $script:shows++ }
$seed = 'https://sf.taobao.com/list/50025969__2.htm'
$state = @{target_url='__TARGET__';target_id='main';prompted_at='2026-10-18T00:00:00Z';seed_prompted_at='';seed_target_url='';seed_target_id=''}
$solver = @{scopes=@{seed=@{last_request=@{target_url=$seed}}}}
Show-Pc1RecoverySeedPrompt -State $state -StatePath 'unused' -SolverStatus $solver -DeferPresentation
if ($script:shows -ne 0 -or $script:reads -ne 0) { throw 'Deferred prompt touched browser' }
if ($script:saved.status -ne 'waiting_for_seed_auth' -or $script:saved.seed_target_url -ne $seed) { throw 'Pending target not persisted' }
# Reload like the next scheduled poll; then repeat to check durable deduplication.
$state = @{}
$script:saved.psobject.Properties | ForEach-Object { $state[$_.Name] = $_.Value }
foreach ($poll in 1..3) {
    Show-Pc1RecoverySeedPrompt -State $state -StatePath 'unused' -SolverStatus $solver
}
@{shows=$script:shows;recorded=[bool]$script:saved.seed_prompted_at} | ConvertTo-Json -Compress
"""
    target = (
        "https://sf.taobao.com/list/50025969__2.htm"
        if same_target
        else "https://sf-item.taobao.com/sf_item/123456789.htm"
    )
    script = script.replace("__POLICY__", str(policy).replace("'", "''")).replace(
        "__TARGET__", target
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "shows": 0 if same_target else 1,
        "recorded": True,
    }


def test_watcher_passes_per_poll_presentation_budget():
    watcher = (
        Path(__file__).resolve().parents[2] / "scripts/watch-pc1-nas-auth-recovery.ps1"
    ).read_text(encoding="utf-8")
    assert "$presentedThisPoll = $false" in watcher
    assert "$presentedThisPoll = $true" in watcher
    assert "-DeferPresentation:$presentedThisPoll" in watcher
