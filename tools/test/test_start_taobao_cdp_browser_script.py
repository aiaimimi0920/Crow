from __future__ import annotations

from pathlib import Path

from tools.test.powershell_script_test_support import read_powershell_script_tree


REPO_ROOT = Path(__file__).resolve().parents[2]


def _browser_script() -> str:
    return read_powershell_script_tree(
        REPO_ROOT.joinpath("scripts", "start-taobao-cdp-browser.ps1")
    )


def test_start_taobao_cdp_browser_script_opens_visible_cdp_browser_when_missing() -> None:
    script = _browser_script()

    assert "Resolve-CrowProjectDataRoot" in script
    assert "docker.local.env" in script
    assert "PSScriptRoot" in script
    assert '"FPFData"' in script
    assert "C:\\Users\\Public\\nas_home\\AI\\FPFData" not in script
    assert "edge-cdp-profile" in script
    assert '[string]$StartUrl = "https://sf.taobao.com/"' in script
    assert "Microsoft\\Edge\\Application\\msedge.exe" in script
    assert "Google\\Chrome\\Application\\chrome.exe" in script
    assert "Invoke-CdpWebRequest" in script
    assert "Start-Process" in script
    assert "--remote-debugging-port=$Port" in script
    assert '[string]$DebuggingAddress = "0.0.0.0"' in script
    assert "--remote-debugging-address=$resolvedDebuggingAddress" in script
    assert "[switch]$HumanAuthMode" in script
    assert "--remote-allow-origins=*" in script
    assert "--no-proxy-server" in script
    assert "/json/version" in script
    assert "192.168.65.254" in script
    assert "Log in to Taobao" in script


def test_start_taobao_cdp_browser_can_use_system_proxy_when_requested() -> None:
    script = _browser_script()

    assert "[switch]$UseSystemProxy" in script
    assert "if (-not $UseSystemProxy)" in script
    assert '$arguments += "--no-proxy-server"' in script


def test_start_taobao_cdp_browser_force_new_stops_existing_cdp_profile_processes() -> None:
    script = _browser_script()

    assert "function Stop-ExistingCdpBrowser" in script
    assert "function Get-CdpBrowserProcesses" in script
    assert "Get-CimInstance Win32_Process" in script
    assert "remote-debugging-port=$Port" in script
    assert "$ProfileDir" in script
    assert "Stop-Process" in script
    assert "AddSeconds(60)" in script
    assert "Start-Sleep -Milliseconds 500" in script
    assert "if ($ForceNew)" in script


def test_start_taobao_cdp_browser_pc2_recovery_can_avoid_cim_process_enumeration() -> None:
    script = _browser_script()

    assert "[switch]$TerminateAllBrowserProcesses" in script
    assert "[switch]$AllBrowserProcesses" in script
    assert 'Get-Process -Name "chrome", "msedge"' in script
    assert "-AllBrowserProcesses:$TerminateAllBrowserProcesses" in script


def test_start_taobao_cdp_browser_existing_cdp_endpoint_opens_requested_start_url() -> None:
    script = _browser_script()

    assert "function Open-CdpBrowserPage" in script
    assert "[System.Uri]::EscapeDataString($Url)" in script
    assert "/json/new?$encodedUrl" in script
    assert "/json/activate/$($page.id)" in script
    assert "Open-CdpBrowserPage -Endpoint $hostEndpoint -Url $StartUrl" in script
    assert "Opened auth page in existing CDP browser" in script


def test_start_taobao_cdp_browser_bypasses_system_proxy_for_loopback_cdp_calls() -> None:
    script = _browser_script()

    assert "function Invoke-CdpWebRequest" in script
    assert "[System.Net.HttpWebRequest]::Create" in script
    assert "$request.Proxy = $null" in script
    assert "Invoke-CdpWebRequest -Uri \"$($Endpoint.TrimEnd('/'))/json/version\"" in script
    assert "Invoke-CdpWebRequest -Method 'PUT'" in script


def test_start_taobao_cdp_browser_bounds_cdp_response_reads() -> None:
    script = _browser_script()

    assert "ReadToEnd()" not in script
    assert "MaxResponseBytes" in script
    assert "ContentLength" in script
    assert "ReadTimeout" in script


def test_start_taobao_cdp_browser_falls_back_when_cdp_new_url_times_out() -> None:
    script = _browser_script()

    assert "function Open-BrowserProcessPage" in script
    assert "Open-CdpBrowserPage -Endpoint $hostEndpoint -Url $StartUrl" in script
    assert "Open-BrowserProcessPage -Browser $browser -ProfileDir $ProfileDir -Port $Port -DebuggingAddress $resolvedDebuggingAddress -Url $StartUrl" in script
    assert "CDP /json/new open failed; falling back to browser process URL open" in script
    assert "Opened auth page via browser process fallback" in script


def test_start_taobao_cdp_browser_uses_process_open_for_long_punish_urls() -> None:
    script = _browser_script()

    assert "function Test-BrowserProcessOpenPreferred" in script
    assert "_____tmd_____/punish" in script
    assert "x5secdata=" in script
    assert "$Url.Length -gt 1800" in script
    assert "if (Test-BrowserProcessOpenPreferred -Url $StartUrl)" in script
    assert "Skipping CDP /json/new for challenge-sized auth URL" in script


def test_start_taobao_cdp_browser_process_detection_includes_edge_and_chrome() -> None:
    script = _browser_script()

    assert '$browserProcessNames = @("chrome.exe", "msedge.exe")' in script


def test_start_taobao_cdp_browser_existing_cdp_endpoint_raises_existing_browser_window() -> None:
    script = _browser_script()

    assert "function Show-CdpBrowserWindow" in script
    assert "ShowWindowAsync" in script
    assert "SetForegroundWindow" in script
    assert "Show-CdpBrowserWindow -Port $Port -ProfileDir $ProfileDir" in script


def test_start_taobao_cdp_browser_new_browser_path_also_raises_window_after_startup() -> None:
    script = _browser_script()

    assert script.count("Show-CdpBrowserWindow -Port $Port -ProfileDir $ProfileDir") >= 2


def test_start_taobao_cdp_browser_restarts_stale_process_when_endpoint_is_unavailable() -> None:
    script = _browser_script()

    assert "staleProcesses = @(Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir)" in script
    assert "Existing CDP browser process exists but endpoint is unavailable" in script
    assert "Stop-ExistingCdpBrowser -Port $Port -ProfileDir $ProfileDir -Endpoint $hostEndpoint" in script
    assert "Stale CDP browser processes did not exit cleanly" in script


def test_start_taobao_cdp_browser_keeps_top_level_filter_for_window_activation_only() -> None:
    script = _browser_script()

    assert "[switch]$TopLevelOnly" in script
    assert 'if ($TopLevelOnly)' in script
    assert '$cmd -like "* --type=*"' in script
    assert "return $false" in script
    show_window = script[
        script.index("function Show-CdpBrowserWindow") : script.index("function Stop-ExistingCdpBrowser")
    ]
    stop_existing = script[
        script.index("function Stop-ExistingCdpBrowser") : script.index("function Find-BrowserExecutable")
    ]
    assert "Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir -TopLevelOnly" in show_window
    assert "Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir -TopLevelOnly" not in stop_existing


def test_start_taobao_cdp_browser_force_new_aborts_if_old_browser_does_not_exit() -> None:
    script = _browser_script()

    assert "return $false" in script
    assert "return $true" in script
    assert "if (-not (Stop-ExistingCdpBrowser -Port $Port -ProfileDir $ProfileDir -Endpoint $hostEndpoint))" in script
    assert "Existing CDP browser processes did not exit cleanly" in script


def test_start_taobao_cdp_browser_force_new_status_messages_do_not_pollute_boolean_return() -> None:
    script = _browser_script()

    assert 'Write-Host "Stopping existing CDP browser processes for port $Port / profile $ProfileDir."' in script
    assert 'Write-Host "Timed out waiting for matching CDP browser processes and endpoint to exit."' in script
    assert 'Write-Output "Stopping existing CDP browser processes for port $Port / profile $ProfileDir."' not in script
    assert 'Write-Output "Timed out waiting for matching CDP browser processes and endpoint to exit."' not in script


def test_start_taobao_cdp_browser_waits_for_endpoint_readiness_with_deadline() -> None:
    script = _browser_script()

    assert "function Wait-CdpEndpoint" in script
    assert "[int]$CdpStartupTimeoutSeconds = 30" in script
    assert "TimeoutSeconds = 30" in script
    assert "PollMilliseconds = 500" in script
    assert "Wait-CdpEndpoint -Endpoint $hostEndpoint -TimeoutSeconds $CdpStartupTimeoutSeconds" in script
    assert "within $CdpStartupTimeoutSeconds seconds" in script
    assert "Start-Sleep -Seconds 3" not in script


def test_start_taobao_cdp_browser_serializes_profile_startup_across_processes() -> None:
    script = _browser_script()

    assert "FapaiFangTaobaoCdp-$Port" in script
    assert "[System.Threading.Mutex]::new" in script
    assert "WaitOne" in script
    assert "AbandonedMutexException" in script
    assert "ReleaseMutex" in script
    assert "Dispose" in script


def test_start_taobao_cdp_browser_ensure_only_does_not_replace_existing_page() -> None:
    script = _browser_script()

    assert "[switch]$EnsureOnly" in script
    assert "if (-not $EnsureOnly)" in script
    assert "CDP endpoint is already healthy; ensure-only mode will not open a page" in script


def test_start_taobao_cdp_browser_force_new_waits_for_endpoint_shutdown_and_all_profile_processes() -> None:
    script = _browser_script()

    assert '[Parameter(Mandatory = $true)][string]$Endpoint' in script
    assert "Stop-ExistingCdpBrowser -Port $Port -ProfileDir $ProfileDir -Endpoint $hostEndpoint" in script
    assert '$remaining = @(Get-CdpBrowserProcesses -Port $Port -ProfileDir $ProfileDir -AllBrowserProcesses:$AllBrowserProcesses)' in script
    assert 'if (($remaining.Count -eq 0) -and -not (Test-CdpEndpoint -Endpoint $Endpoint))' in script
    assert 'Timed out waiting for matching CDP browser processes and endpoint to exit.' in script


def test_start_taobao_cdp_browser_supports_isolated_profile_and_optional_extension_disable() -> None:
    script = _browser_script()

    assert "[switch]$IsolatedProfile" in script
    assert "[switch]$DisableExtensions" in script
    assert "edge-cdp-profile-isolated" in script
    assert 'if ($IsolatedProfile)' in script
    assert 'if ($DisableExtensions)' in script
    assert '$arguments += "--disable-extensions"' in script


def test_start_taobao_cdp_browser_supports_minimized_recovery_and_visible_manual_windows() -> None:
    script = _browser_script()

    assert "[switch]$StartMinimized" in script
    assert "if ($StartMinimized)" in script
    assert '$arguments += "--start-minimized"' in script
    assert script.count("-WindowStyle Normal") >= 2


def test_start_taobao_cdp_browser_includes_low_noise_edge_flags_from_legacy_recovery_flow() -> None:
    script = _browser_script()

    assert "--disable-background-networking" in script
    assert "--disable-sync" in script
    assert "--disable-client-side-phishing-detection" in script
    assert "--disable-default-apps" in script
    assert "--disable-blink-features=AutomationControlled" in script


def test_operator_docs_include_cdp_browser_startup_helper() -> None:
    readme = REPO_ROOT.joinpath("README.md").read_text(encoding="utf-8")

    assert "start-taobao-cdp-browser.ps1" in readme
    assert ".\\CrowData\\edge-cdp-profile" in readme
    assert "http://192.168.65.254:9223" in readme


def test_open_remote_auth_browser_script_prefers_pc2_remote_helper_and_falls_back_locally() -> None:
    script = REPO_ROOT.joinpath("scripts", "open-remote-auth-browser.ps1").read_text(encoding="utf-8")

    assert "FAPAI_REMOTE_AUTH_HOST" in script
    assert "FAPAI_REMOTE_AUTH_USER" in script
    assert "FAPAI_REMOTE_AUTH_PASSWORD" in script
    assert "C:\\fapaifang-worker\\ops\\trigger-open-auth-task.ps1" in script
    assert "edge-cdp-profile-pc2" in script
    assert "paramiko" in script
    assert "Get-Command python" in script
    assert "exec_command" in script
    assert "trigger-open-auth-task.ps1" in script
    assert "-StartUrl" in script
    assert "-ProfileDir" in script
    assert "falling back to local auth browser helper" in script
    assert 'Join-Path $PSScriptRoot "start-taobao-cdp-browser.ps1"' in script
    assert "New-TemporaryFile" in script
    assert "Remove-Item" in script
    assert '-c $pythonCode' not in script


def test_pc1_manual_auth_session_uses_normal_chrome_and_persists_handoff_state() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-pc1-manual-auth-session.ps1").read_text(encoding="utf-8")

    assert "manual_browser_without_cdp" in script
    assert "pc1-manual-auth-state.json" in script
    assert '"--user-data-dir=$resolvedProfileDir"' in script
    assert '"--no-first-run"' in script
    assert "Start-Process" in script
    assert "Stop-ProfileBrowser" in script
    assert "--remote-debugging-port=$DebugPort" in script
    assert "start_url = $StartUrl" in script


def test_local_bridge_auth_keeps_one_cdp_browser_and_uses_port_9225() -> None:
    script = REPO_ROOT.joinpath("scripts", "open-remote-auth-browser.ps1").read_text(encoding="utf-8")

    assert "start-pc1-auth-bridge.ps1" in script
    assert "FAPAI_AUTH_BRIDGE_SCRIPT" in script
    assert '"-LocalCdpPort",\n        "9225"' in script
    assert '"-RemoteCdpPort",\n        "9225"' in script
    assert "Start-LocalAuthAutoResumeWatcher" in script


def test_check_taobao_login_health_script_starts_browser_and_runs_safe_helper() -> None:
    script = REPO_ROOT.joinpath("scripts", "check-taobao-login-health.ps1").read_text(encoding="utf-8")

    assert "start-taobao-cdp-browser.ps1" in script
    assert "tools\\taobao_login_health.py" in script
    assert ".ProviderPath" in script
    assert "http://127.0.0.1:$Port" in script
    assert "https://sf.taobao.com/list/50025969__2.htm" in script
    assert "--open-login" in script
    assert "[switch]$TriggerCaptchaSolver" in script
    assert "if ($TriggerCaptchaSolver)" in script
    assert '$healthArgs += "--trigger-captcha-solver"' in script
    assert '"--trigger-captcha-solver",' not in script
    assert "--wait-seconds" in script
    assert "--poll-seconds" in script
    assert "Invoke-WebRequest" in script
    assert "StartBrowser" in script
    assert "SkipBrowserStart" in script


def test_check_taobao_login_health_script_can_forward_isolated_profile_flags() -> None:
    script = REPO_ROOT.joinpath("scripts", "check-taobao-login-health.ps1").read_text(encoding="utf-8")

    assert "[switch]$IsolatedProfile" in script
    assert "[switch]$DisableExtensions" in script
    assert 'if ($IsolatedProfile)' in script
    assert 'if ($DisableExtensions)' in script
    assert '@("-IsolatedProfile")' in script
    assert '@("-DisableExtensions")' in script


def test_operator_docs_include_login_health_recovery_helper() -> None:
    readme = REPO_ROOT.joinpath("README.md").read_text(encoding="utf-8")

    assert "check-taobao-login-health.ps1" in readme
    assert "taobao_login_health.py" in readme
    assert "login_recovery" in readme
    assert "punish" in readme
    assert "验证码" in readme
    assert "http://127.0.0.1:9223" in readme


def test_export_taobao_cookie_snapshot_script_starts_browser_and_does_not_print_values() -> None:
    script = REPO_ROOT.joinpath("scripts", "export-taobao-cookie-snapshot.ps1").read_text(encoding="utf-8")

    assert "start-taobao-cdp-browser.ps1" in script
    assert "browserless_seed_probe.py" in script
    assert "--write-cookie-snapshot" in script
    assert "Resolve-CrowProjectDataRoot" in script
    assert "taobao-cookies.json" in script
    assert "FAPAI_AUTH_LOCAL_CDP_PORT" in script
    assert "http://127.0.0.1:$resolvedPort" in script
    assert "load_cookie_snapshot" in script
    assert "summarize_cookie_snapshot" in script
    assert "ConvertTo-Json" in script
    assert "cookie value" in script
    assert "PYTHONPATH" in script
    assert "$summaryScript" in script
    assert "summary['path']" in script
    assert "summary.pop('names', None)" in script
    assert "Complete-ManualBrowserHandoff" in script
    assert "pc1-manual-auth-state.json" in script
    assert 'StartUrl "about:blank"' in script


def test_export_taobao_cookie_snapshot_script_can_forward_isolated_profile_flags() -> None:
    script = REPO_ROOT.joinpath("scripts", "export-taobao-cookie-snapshot.ps1").read_text(encoding="utf-8")

    assert "[switch]$IsolatedProfile" in script
    assert "[switch]$DisableExtensions" in script
    assert 'if ($IsolatedProfile)' in script
    assert 'if ($DisableExtensions)' in script
    assert '@("-IsolatedProfile")' in script
    assert '@("-DisableExtensions")' in script


def test_export_taobao_cookie_snapshot_validates_candidate_before_promoting_official_file() -> None:
    script = REPO_ROOT.joinpath("scripts", "export-taobao-cookie-snapshot.ps1").read_text(encoding="utf-8")

    assert "$candidatePath" in script
    assert "--write-cookie-snapshot $candidatePath" in script
    assert "FAPAI_COOKIE_SNAPSHOT_CANDIDATE" in script
    assert "FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS_JSON" in script
    assert "browserless_seed_probe.probe_seed_page" in script
    assert "taobao_login_health.classify_taobao_health" in script
    assert "Move-Item -LiteralPath $candidatePath -Destination $OutputPath -Force" in script
    assert "official snapshot was not overwritten" in script


def test_export_taobao_cookie_snapshot_requires_manual_detail_page_health() -> None:
    script = REPO_ROOT.joinpath("scripts", "export-taobao-cookie-snapshot.ps1").read_text(encoding="utf-8")

    assert "[string[]]$DetailSampleUrl" in script
    assert "ConvertTo-CanonicalDetailSampleUrl" in script
    assert "FAPAI_COOKIE_SNAPSHOT_DETAIL_SAMPLE_URLS_JSON" in script
    assert "ConvertTo-Json -InputObject @($detailSampleUrls) -Compress" in script
    assert "live_batch_smoke.fetch_detail_with_browser" in script
    assert '"detail_health_required": detail_health_required' in script
    assert '"detail_health_satisfied": detail_health_satisfied' in script
    assert '"healthy": healthy_samples > 0 and detail_health_satisfied' in script
    assert "list/detail health validation" in script


def test_export_taobao_cookie_snapshot_redacts_candidate_health_failure_output() -> None:
    script = REPO_ROOT.joinpath("scripts", "export-taobao-cookie-snapshot.ps1").read_text(encoding="utf-8")

    assert "taobao_login_health.redact_taobao_health_output(payload)" in script
    assert 'public_payload.pop("candidate_path", None)' in script
    assert 'public_payload.pop("cookie_summary", None)' in script
    assert "x5secdata" not in script
    assert "cookie2=" not in script
    assert "sgcookie=" not in script
    assert "_tb_token_=" not in script


def test_complete_pc1_inplace_auth_script_can_allow_list_only_auto_resume() -> None:
    script = REPO_ROOT.joinpath("scripts", "complete-pc1-inplace-auth.ps1").read_text(encoding="utf-8")

    assert "[switch]$AllowListOnly" in script
    assert '"--allow-list-only"' in script


def test_pc1_auth_auto_resume_watcher_retries_cookie_export_and_posts_auth_complete() -> None:
    script = REPO_ROOT.joinpath("scripts", "watch-pc1-auth-auto-resume.ps1").read_text(encoding="utf-8")

    assert "complete-pc1-inplace-auth.ps1" in script
    assert "-AllowListOnly" in script
    assert "/collection/auth/complete" in script
    assert "pc1_auth_auto_resume_watch" in script
    assert "pc1-auth-auto-resume-state.json" in script
    assert "pc1-auth-auto-resume.log" in script


def test_operator_docs_recommend_isolated_taobao_browser_profile_for_recovery() -> None:
    readme = REPO_ROOT.joinpath("README.md").read_text(encoding="utf-8")

    assert "edge-cdp-profile-isolated" in readme
    assert "-IsolatedProfile" in readme
    assert "-DisableExtensions" in readme
