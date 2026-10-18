from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tools import taobao_inplace_auth_handoff as handoff


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows PowerShell required")
@pytest.mark.parametrize("prompted_at", ["2020-01-01T00:00:00Z", "2099-01-01T00:00:00Z", "invalid-timestamp"])
def test_existing_recovery_never_schedules_another_background_prompt(prompted_at):
    policy = Path(__file__).resolve().parents[2] / "scripts/pc1-auth-recovery-policy.ps1"
    script = f". '{str(policy).replace(chr(39), chr(39) * 2)}'; " + (
        f"Test-Pc1RecoveryPromptDue -SameRecovery $true -PromptedAt '{prompted_at}'"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=15, check=True)
    assert result.stdout.strip() == "False"


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows PowerShell required")
def test_background_auth_prompt_never_creates_a_modal_popup():
    policy = Path(__file__).resolve().parents[2] / "scripts/pc1-auth-recovery-policy.ps1"
    script = r"""
$ErrorActionPreference = 'Stop'
. '__POLICY__'
$script:comAttempts = 0
$script:windowShows = 0
function New-Object { $script:comAttempts++; throw 'COM must not be used for background auth' }
function Invoke-CdpWebRequest { }
function Show-CdpBrowserWindow { $script:windowShows++ }
$presentation = Show-Pc1RecoveryPrompt -Endpoint 'http://localhost:9225' -TargetId 'selected' -Port 9225 -ProfileDir 'unused'
@{comAttempts=$script:comAttempts;windowShows=$script:windowShows;activated=$presentation.tab_activated} | ConvertTo-Json -Compress
""".replace("__POLICY__", str(policy).replace("'", "''"))
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=15, check=True)
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data == {"comAttempts": 0, "windowShows": 1, "activated": True}


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows PowerShell required")
def test_watcher_persists_presentation_attempt_even_when_foreground_fails():
    policy = Path(__file__).resolve().parents[2] / "scripts/pc1-auth-recovery-policy.ps1"
    script = r"""
$ErrorActionPreference = 'Stop'
. '__POLICY__'
$watcher = Join-Path (Split-Path '__POLICY__' -Parent) 'watch-pc1-nas-auth-recovery.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($watcher, [ref]$null, [ref]$null)
$branch = $ast.Find({param($node) $node -is [Management.Automation.Language.IfStatementAst] -and
    $node.Extent.Text.StartsWith('if ($null -ne $authTab -and (Test-Pc1RecoveryPromptDue')}, $true)
if ($null -eq $branch) { throw 'Presentation branch not found' }
$block = [scriptblock]::Create($branch.Extent.Text)
$script:persisted = $null
$script:shows = 0
function Write-State { param($Path, $State); $script:persisted = $State | ConvertTo-Json | ConvertFrom-Json }
function Test-CurrentAutomaticRecovery { return $true }
function Show-Pc1RecoveryPrompt {
    if (-not $script:persisted.prompted_at) { throw 'Attempt was not persisted before presentation' }
    $script:shows++
    return @{tab_activated=$false;window_shown=$false}
}
$authTab = @{id='selected'}
$sameRecovery = $true
$statePath = 'unused'
$cdpEndpoint = 'http://localhost:9225'
$Port = 9225
$ProfileDir = 'unused'
foreach ($poll in 1..3) {
    $newState = @{prompted_at=[string]$script:persisted.prompted_at}
    . $block
}
@{shows=$script:shows;recorded=[bool]$script:persisted.prompted_at} | ConvertTo-Json -Compress
""".replace("__POLICY__", str(policy).replace("'", "''"))
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=15, check=True)
    assert json.loads(result.stdout) == {"shows": 1, "recorded": True}


def _pages(monkeypatch, requested_html: str = "blocked") -> list[str]:
    targets = [
        {"id": "selected", "type": "page", "webSocketDebuggerUrl": "ws://selected"},
        {"id": "other", "type": "page", "webSocketDebuggerUrl": "ws://other"},
    ]
    inspected: list[str] = []

    def evaluate(url, _expression):
        inspected.append(url)
        html = requested_html if url == "ws://selected" else "healthy"
        value = {"html": html + "x" * 1200,
                 "url": "https://sf-item.taobao.com/sf_item/123456789.htm"}
        return {"result": {"result": {"value": json.dumps(value)}}}

    monkeypatch.setattr(handoff.taobao_login_health, "list_cdp_targets", lambda _: targets)
    monkeypatch.setattr(handoff.taobao_login_health, "evaluate_cdp_expression", evaluate)
    monkeypatch.setattr(handoff.browserless_seed_probe, "summarize_list_page",
                        lambda html, **_: {"body_has_challenge": html.startswith("blocked")})
    return inspected


def test_selected_challenge_cannot_be_completed_by_another_healthy_tab(monkeypatch, tmp_path):
    inspected = _pages(monkeypatch)
    official = tmp_path / "cookies.json"
    official.write_text("preserved", encoding="utf-8")
    with pytest.raises(RuntimeError, match="No healthy open"):
        handoff.complete_inplace_auth(cdp_endpoint="http://localhost:9225",
                                     output_path=official, required_target_id="selected")
    assert inspected == ["ws://selected"]
    assert official.read_text(encoding="utf-8") == "preserved"


def test_closed_selected_tab_does_not_fall_back_to_another_tab(monkeypatch):
    inspected = _pages(monkeypatch)
    with pytest.raises(RuntimeError, match="No healthy open"):
        handoff._healthy_open_taobao_page("http://localhost:9225", required_target_id="closed")
    assert not inspected


def test_selected_detail_passes_only_after_its_challenge_is_gone(monkeypatch):
    inspected = _pages(monkeypatch, "healthy")
    page = handoff._healthy_open_taobao_page("http://localhost:9225",
        required_target_id="selected", require_detail=True)
    assert page["kind"] == "detail"
    assert inspected == ["ws://selected"]


def test_list_page_cannot_satisfy_detail_recovery(monkeypatch):
    monkeypatch.setattr(handoff.taobao_login_health, "list_cdp_targets", lambda _: [
        {"id": "selected", "type": "page", "webSocketDebuggerUrl": "ws://selected"}])
    monkeypatch.setattr(handoff.taobao_login_health, "evaluate_cdp_expression", lambda *_: {
        "result": {"result": {"value": json.dumps({"html": "healthy" * 300,
            "url": "https://sf.taobao.com/list/50025969__2.htm"})}}})
    monkeypatch.setattr(handoff.browserless_seed_probe, "summarize_list_page",
                        lambda *_args, **_kwargs: {"has_script": True})
    with pytest.raises(RuntimeError, match="No healthy open"):
        handoff._healthy_open_taobao_page("http://localhost:9225",
            required_target_id="selected", require_detail=True)


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows PowerShell required")
def test_recovery_target_selection_and_visible_prompt_policy():
    policy = Path(__file__).resolve().parents[2] / "scripts/pc1-auth-recovery-policy.ps1"
    script = r"""
$ErrorActionPreference = 'Stop'
. '__POLICY__'
$url = 'https://sf-item.taobao.com/sf_item/123456789.htm'
$solver = @{scopes=@{detail=@{last_request=@{target_url=($url+'/_____tmd_____/punish?secret=not-copied')}}}}
$tabs = @(
    @{id='healthy';type='page';url=$url},
    @{id='challenge';type='page';url=($url+'/_____tmd_____/punish')},
    @{id='lookalike';type='page';url='https://sf-item.taobao.com.attacker.test/sf_item/123456789.htm'}
)
$now = [DateTimeOffset]::Parse('2026-09-05T12:00:00Z')
$result = @{
    target = Get-Pc1RecoveryTargetUrl -SolverStatus $solver -FallbackUrl 'https://sf.taobao.com/'
    selected = (Get-Pc1RecoveryTab -Tabs $tabs -TargetUrl $url).id
    preserved = (Get-Pc1RecoveryTab -Tabs $tabs -TargetUrl $url -PreferredId 'healthy').id
    rejectLookalike = $null -eq (Get-Pc1RecoveryTab -Tabs @($tabs[2]) -TargetUrl $url)
    newRecovery = Test-Pc1RecoveryPromptDue -SameRecovery $false -PromptedAt $now.ToString('o')
    firstPrompt = Test-Pc1RecoveryPromptDue -SameRecovery $true -PromptedAt ''
    noRepeatedFocus = Test-Pc1RecoveryPromptDue -SameRecovery $true -PromptedAt $now.AddSeconds(-60).ToString('o')
    reminder = Test-Pc1RecoveryPromptDue -SameRecovery $true -PromptedAt $now.AddSeconds(-301).ToString('o')
}
$inline = @{id='inline';type='page';url=$url;title=(-join [char[]]@(0x9a8c,0x8bc1,0x7801,0x62e6,0x622a))}
$result.inlineChallenge = (Get-Pc1RecoveryTab -Tabs @($tabs[0],$inline) -TargetUrl $url).id
$result.existingInlineChallenge = (Get-Pc1RecoveryTab -Tabs @($inline) -TargetUrl 'https://sf-item.taobao.com/sf_item/999999999.htm').id
$multiPageJson = ConvertTo-Json -InputObject @($tabs[0], $inline, @{type='worker';url=''}) -Compress
$watcher = Join-Path (Split-Path '__POLICY__' -Parent) 'watch-pc1-nas-auth-recovery.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($watcher, [ref]$null, [ref]$null)
$definition = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-CdpTabs'}, $true)
. ([scriptblock]::Create($definition.Extent.Text))
function Read-TestCdpResponse { $global:LASTEXITCODE = 0; return $multiPageJson }
function Get-Command { return @{Source='Read-TestCdpResponse'} }
$readTabs = @(Get-CdpTabs -Endpoint 'http://localhost:9225')
$result.cdpTabCount = $readTabs.Count
$result.cdpSelected = (Get-Pc1RecoveryTab -Tabs $readTabs -TargetUrl $url).id
Remove-Item Function:\Get-Command
$script:tabReads = 0
function Invoke-CdpWebRequest {
    $script:tabReads++
    $pages = if ($script:tabReads -eq 1) { @(@{type='page';url='about:blank'}) } else { @($tabs[0], $inline) }
    return @{Content=(ConvertTo-Json -InputObject $pages -Compress)}
}
$result.waitedForLoadedTab = (Wait-Pc1RecoveryTab -Endpoint 'http://localhost:9225' -TargetUrl $url -TimeoutSeconds 3).id
$result.tabReads = $script:tabReads
$WarningPreference = 'SilentlyContinue'
function Invoke-CdpWebRequest { throw 'Simulated CDP failure' }
function Show-CdpBrowserWindow { throw 'Simulated desktop failure' }
function New-Object { throw 'Simulated COM failure' }
$presentation = Show-Pc1RecoveryPrompt -Endpoint 'http://localhost:9225' -TargetId 'selected' -Port 9225 -ProfileDir 'unused'
$result.notificationFailureIsNonfatal = -not $presentation.window_shown -and -not $presentation.tab_activated
$result | ConvertTo-Json -Compress
""".replace("__POLICY__", str(policy).replace("'", "''"))
    completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                               capture_output=True, text=True, timeout=30, check=True)
    result = json.loads(completed.stdout)
    assert result == {
        "target": "https://sf-item.taobao.com/sf_item/123456789.htm", "selected": "challenge",
        "preserved": "healthy", "rejectLookalike": True, "newRecovery": True,
        "firstPrompt": True, "noRepeatedFocus": False, "reminder": False,
        "notificationFailureIsNonfatal": True,
        "inlineChallenge": "inline", "existingInlineChallenge": "inline",
        "cdpTabCount": 3, "cdpSelected": "inline",
        "waitedForLoadedTab": "inline", "tabReads": 2,
    }
