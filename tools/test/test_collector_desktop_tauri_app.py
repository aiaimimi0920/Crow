from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "collector-desktop"


def _frontend_js() -> str:
    source_root = APP_ROOT / "src"
    source_files = (
        "desktop_template.ts",
        "desktop_state.ts",
        "desktop_shared.ts",
        "desktop_config.ts",
        "desktop_http.ts",
        "desktop_native.ts",
        "desktop_standardized_fields.json",
        "desktop_regions.ts",
        "desktop_collection_views.ts",
        "desktop_overview.ts",
        "desktop_runtime_controls.ts",
        "desktop_auth.ts",
        "desktop_auth_target.ts",
        "desktop_auth_scope.ts",
        "desktop_actions.ts",
        "main.ts",
    )
    return "\n".join(
        (source_root / name).read_text(encoding="utf-8")
        for name in source_files
    )


def test_collector_desktop_is_independent_tauri_application() -> None:
    package_json = json.loads((APP_ROOT / "package.json").read_text(encoding="utf-8"))
    tauri_config = json.loads((APP_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    cargo_toml = (APP_ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")

    assert package_json["name"] == "crow-collector-desktop"
    assert package_json["private"] is True
    assert "tauri" in package_json["scripts"]
    assert "tauri:dev" in package_json["scripts"]
    assert "tauri:build" in package_json["scripts"]
    assert tauri_config["productName"] == "FapaiFang Collector Console"
    assert tauri_config["app"]["windows"][0]["title"] == "Crow 运维观察台（PC2 采集）"
    assert tauri_config["build"]["frontendDist"] == "../dist"
    assert tauri_config["bundle"]["icon"] == ["icons/icon.ico"]
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    manifest = tomllib.loads(cargo_toml)
    assert manifest["package"]["name"] == "crow_collector_desktop"
    assert manifest["lib"]["name"] == "crow_collector_desktop_lib"
    assert manifest["package"]["default-run"] == "fapaifang_collector_desktop"
    assert manifest["bin"] == [{"name": "fapaifang_collector_desktop", "path": "src/main.rs"}]
    assert 'tauri = { version = "2"' in cargo_toml


def test_collector_desktop_frontend_uses_collection_observer_api_not_browser_page() -> None:
    index_html = (APP_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = _frontend_js()

    assert "Crow 运维观察台（PC2 采集）" in index_html
    assert "链接采集" in main_js
    assert "商品详情" in main_js
    assert "商品分析" in main_js
    assert "/api/collection/overview" in main_js
    assert "/api/collection/items" in main_js
    assert "window.location.href = '/collection'" not in main_js
    assert "http://127.0.0.1:8001" in main_js
    assert "http://192.168.15.200:8001" not in main_js


def test_links_stage_is_operator_focused_and_paginated_to_ten_items() -> None:
    main_js = _frontend_js()

    assert 'limit: 10' in main_js
    assert '<option selected>10</option>' in main_js
    assert "<th>商品编号</th>" in main_js
    assert "<th>链接</th>" in main_js
    assert "<th>地区</th>" in main_js
    assert "<th>状态</th>" in main_js
    assert "链接已采集" in main_js
    assert "详情已采集" in main_js
    assert "AI 已分析" in main_js
    assert "列表来源" not in main_js
    assert "详情/AI文件" not in main_js


def test_details_stage_click_opens_right_side_collected_html_panel() -> None:
    main_js = _frontend_js()

    assert '<aside class="panel detail hidden" id="detailPanel">' in main_js
    assert "已采集 HTML 文本" in main_js
    assert "用于后续 AI 分析" in main_js
    assert "loadDetailHtml" in main_js
    assert 'state.stage === "details"' in main_js
    assert 'detailPanel").classList.add("hidden")' in main_js
    assert "/api/collection/item?item_id=" in main_js
    assert "object(data.artifacts).detail_html" in main_js


def test_analysis_stage_click_opens_standardized_field_table() -> None:
    main_js = _frontend_js()

    assert "AI 标准化数据" in main_js
    assert "条目名称" in main_js
    assert "数值内容" in main_js
    assert "loadAnalysisData" in main_js
    assert "renderStandardizedEntries" in main_js
    assert 'state.stage === "analysis"' in main_js
    assert "flat_item" in main_js
    assert "standardizedRows" in main_js
    assert "成交价格" in main_js
    assert "完整地址" in main_js
    assert "建筑面积" in main_js


def test_analysis_stage_supports_reanalysis_and_manual_edit_update_controls() -> None:
    main_js = _frontend_js()

    assert "AI 分析次数" in main_js
    assert "AI 再分析" in main_js
    assert "手动编辑" in main_js
    assert "取消编辑" in main_js
    assert "手动更新" in main_js
    assert "startManualEdit" in main_js
    assert "cancelManualEdit" in main_js
    assert "submitManualUpdate" in main_js
    assert "requestReanalysis" in main_js
    assert "/api/collection/item/reanalyze" in main_js
    assert "/api/collection/item/manual_update" in main_js
    assert "editable-field" in main_js
    assert "analysisAttemptCount" in main_js


def test_runtime_status_card_exposes_operator_controls_and_auth_challenge_dialog() -> None:
    main_js = _frontend_js()
    tauri_config = json.loads((APP_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    rust_lib = (APP_ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    assert "暂停中" in main_js
    assert "运行中" in main_js
    assert "待认证" in main_js
    assert "已完成" in main_js
    assert "暂停采集" in main_js
    assert "开始采集" in main_js
    assert "认证" in main_js
    assert "打开挑战页面" in main_js
    assert "authChallengeDialog" in main_js
    assert "authChallengeFrame" not in main_js
    assert "toggleRuntimePause" in main_js
    assert "openAuthChallenge" in main_js
    assert 'tryInvoke("desktop_auth_action"' in main_js
    assert "auth_bridge::desktop_auth_action" in rust_lib
    assert "export_taobao_cookie_snapshot" not in rust_lib
    bridge = (APP_ROOT / "src-tauri/src/auth_bridge.rs").read_text(encoding="utf-8")
    assert '"-NoProfile"' in bridge
    assert "creation_flags(0x08000000)" in bridge
    assert "helper_process::run(" in bridge
    helper = (APP_ROOT / "src-tauri/src/helper_process.rs").read_text(encoding="utf-8")
    assert "Stdio::null()" in helper
    assert ".stdout(Stdio::piped())" in helper
    assert ".stderr(Stdio::piped())" in helper
    assert "creation_flags(0x08000000)" in helper
    assert "decode_result(&output.stdout)" in bridge
    assert "CROW_AUTH_RESULT=" in bridge
    assert "desktop-auth-challenge.ps1" in bridge
    assert "spawn_blocking" in bridge
    assert "CROW_AUTH_RESULT=" in bridge
    assert "std::env::current_exe" in rust_lib
    assert "std::env::current_dir" in rust_lib
    assert '.join("scripts")' in rust_lib
    assert "\\\\192.168.15.200\\home\\project\\project\\fapaifang" not in rust_lib
    assert "api/collection/control/${action}" in main_js
    assert "/api/collection/auth/complete" not in main_js
    assert "/api/report_captcha" not in main_js
    assert "frame-src https://*.taobao.com" not in tauri_config["app"]["security"]["csp"]
    assert "auth-stage-row" in main_js
    assert "链接采集" in main_js and "详情采集" in main_js
    assert "engineRestartButton" in main_js
    assert "challenge_metrics" not in main_js


def test_auth_dialog_open_is_passive_and_browser_open_is_explicit() -> None:
    main_js = _frontend_js()

    assert "openAndQueueAuthChallenge" not in main_js
    assert "function normalizeAuthChallengeUrl" in main_js
    assert "_____tmd_____/punish" in main_js
    assert "transient challenge credentials" in main_js
    assert 'parsed.hostname === "sf-item.taobao.com"' in main_js
    assert "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1" in main_js
    auth = (APP_ROOT / "src/desktop_auth.ts").read_text(encoding="utf-8")
    open_function = auth[auth.index("export function openAuthChallenge"):auth.index("async function run")]
    assert 'run("open")' not in open_function
    assert "control/pause" not in auth
    assert 'return run("open")' in auth


def test_auth_challenge_default_url_is_sanitized_before_native_handoff() -> None:
    main_js = _frontend_js()

    scoped_target = (APP_ROOT / "src/desktop_auth_scope.ts").read_text(encoding="utf-8")
    assert "normalizeAuthChallengeUrl(candidate)" in scoped_target
    assert "target_url: authScopeTarget(state.lastOverview, scope" in main_js
    helper = (REPO_ROOT / "tools/pc1_desktop_auth.py").read_text(encoding="utf-8")
    assert "target_identity(url)" in helper
    assert 'url.scheme != "https"' in helper
    assert "url.username or url.password" in helper


def test_auth_challenge_manual_mode_never_submits_background_solver_request() -> None:
    main_js = _frontend_js()

    assert "function buildSolverReportPayload" not in main_js
    assert "/api/report_captcha" not in main_js

    assert "queueAuthChallenge" not in main_js
    assert "提交认证任务" not in main_js
    helper = (REPO_ROOT / "tools/pc1_desktop_auth.py").read_text(encoding="utf-8")
    assert '"-HumanAuthMode"' in helper
    assert "required_target_id=selected" in helper


def test_auth_challenge_network_is_bounded_and_completion_waits_for_verification() -> None:
    main_js = _frontend_js()

    assert "function fetchWithTimeout" in main_js
    assert "AbortController" in main_js
    assert "timeoutMs" in main_js
    assert 'run(phase === "pending_pc2" ? "status" : "complete")' in main_js
    assert "if (result.completed)" in main_js
    assert "refresh_cookie_snapshot" not in main_js
    client = (REPO_ROOT / "tools/pc1_desktop_recovery.py").read_text(encoding="utf-8")
    assert "timeout=20" in client
    assert "NoRedirect" in client


def test_tauri_inplace_auth_uses_port_9225_without_browser_restart_switch() -> None:
    helper = (REPO_ROOT / "tools/pc1_desktop_auth.py").read_text(encoding="utf-8")
    assert "handoff.complete_inplace_auth" in helper
    assert 'environment_value("CROW_AUTH_LOCAL_CDP_PORT", environment=environment, root=ROOT) or 9225' in helper
    assert '"-ForceNew"' not in helper


def test_collector_desktop_frontend_can_run_as_plain_html_console() -> None:
    main_js = _frontend_js()
    tauri_config = json.loads((APP_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

    assert "function isTauriRuntime()" in main_js
    assert "function defaultBrowserApiBase()" in main_js
    assert "window.location.origin" in main_js
    assert 'value="${defaultBrowserApiBase()}"' in main_js
    assert 'startupApiBase(() => tryInvoke("default_api_base"), defaultBrowserApiBase)' in main_js
    assert "state.apiBase = initialConfig.apiBase" in main_js
    assert "setConfigurationBlocked(initialConfig.blocked)" in main_js
    assert "not running inside Tauri" in main_js
    assert 'window.open(current.target_url, "_blank", "noopener,noreferrer")' in main_js
    assert "普通浏览器无法读取挑战窗口的 cookie" in main_js
    assert "http://127.0.0.1:8001" in tauri_config["app"]["security"]["csp"]
    assert "http://192.168.15.200:8001" not in tauri_config["app"]["security"]["csp"]


def test_runtime_start_preserves_authentication_and_restart_is_separate() -> None:
    main_js = _frontend_js()

    assert 'paused ? "开始采集" : "暂停采集"' in main_js
    assert "forceStartCollection" not in main_js
    toggle_function = main_js[
        main_js.index("async function toggleRuntimePause"):
        main_js.index("async function requestEngineRestart")
    ]
    assert "dataset.action" in toggle_function
    assert 'await post(base, action, {}, element<HTMLInputElement>("restartToken").value.trim())' in toggle_function
    assert "/auth/complete" not in toggle_function
    assert 'X-FAPAI-Control-Token' in main_js
    assert 'await decision !== "confirm"' in main_js


def test_runtime_state_prefers_server_provided_runtime_state_before_solver_fallback() -> None:
    main_js = _frontend_js()

    runtime_function = main_js[
        main_js.index("function runtimeStateFromOverview"):
        main_js.index("async function loadOverview")
    ]
    assert "data.runtime_state" in runtime_function
    assert 'return data.runtime_state;' in runtime_function
    assert "solver.manual_required" in runtime_function
    assert "solver.force_unlock_flag_exists" in runtime_function
    assert "solver.running || solver.manual_required" not in runtime_function


def test_runtime_state_fallback_keeps_running_for_detail_only_auth_when_seed_stage_can_continue() -> None:
    main_js = _frontend_js()

    runtime_function = main_js[
        main_js.index("function runtimeStateFromOverview"):
        main_js.index("async function loadOverview")
    ]
    assert "last_request" in runtime_function
    assert "target_url" in runtime_function
    assert 'authTargetScope(targetUrl) === "detail"' in runtime_function
    assert "seed_scan_job_pending" in runtime_function
    assert "seed_scan_progress_pending" in runtime_function
    assert 'return "运行中";' in runtime_function


def test_collector_desktop_auto_refreshes_every_sixty_seconds() -> None:
    main_js = _frontend_js()

    assert "AUTO_REFRESH_INTERVAL_MS = 60_000" in main_js
    assert "setInterval" in main_js
    assert "AUTO_REFRESH_INTERVAL_MS" in main_js
    assert "refreshInFlight" in main_js
    assert "最后刷新" in main_js
    assert "autoRefreshStatus" in main_js
    assert 'reloadAll({ silent: true })' in main_js
    reload_all_function = main_js[
        main_js.index("async function reloadAll"):
        main_js.index('document.querySelectorAll<HTMLButtonElement>("button[data-stage]")')
    ]
    assert "await loadOverview()" in reload_all_function
    assert "await loadItems()" in reload_all_function
    assert "await loadRegions()" not in reload_all_function


def test_collector_desktop_current_challenge_is_independent_and_overview_cannot_overwrite_handoff() -> None:
    main_js = _frontend_js()

    assert "authWatcherStatusMessage" not in main_js
    assert "function challengeActive" in main_js
    assert "solver.scopes || solver.collection_scopes" in main_js
    assert "force_reset_required" in main_js
    views = (APP_ROOT / "src/desktop_collection_views.ts").read_text(encoding="utf-8")
    assert '$("authChallengeStatus")' not in views


def test_collector_desktop_refreshes_region_status_separately_every_ten_minutes() -> None:
    main_js = _frontend_js()

    assert "REGION_REFRESH_INTERVAL_MS = 600_000" in main_js
    assert "refreshRegions" in main_js
    assert "刷新所在地" in main_js
    assert "regionRefreshStatus" in main_js
    assert "requestId === state.regionsRequestId" in main_js
    assert "最后刷新所在地" in main_js
    assert 'setInterval(() => { if (!isConfigurationBlocked()) void loadRegions({ silent: true }); }, REGION_REFRESH_INTERVAL_MS)' in main_js
    assert '$("refreshRegions").addEventListener("click", () => loadRegions({ silent: false }))' in main_js
    assert "每 10 分钟自动刷新所在地状态" in main_js


def test_collector_desktop_overview_cards_show_recent_sixty_second_growth() -> None:
    main_js = _frontend_js()

    assert "function minuteGrowth" in main_js
    assert "statistics.minute_delta" in main_js
    assert "统计暂未更新" in main_js
    assert "等待分钟采样" not in main_js
    assert '["links", "unique_items"]' in main_js
    assert '["details", "captured"]' in main_js
    assert '["analysis", "finalized"]' in main_js
    assert "now - 60_000" in main_js
    assert "perMinute" not in main_js


def test_collector_desktop_has_stage_specific_region_tabs_and_link_reset_control() -> None:
    main_js = _frontend_js()
    styles = (APP_ROOT / "src" / "styles.css").read_text(encoding="utf-8")
    styles += "\n".join(
        (APP_ROOT / "src" / relative).read_text(encoding="utf-8")
        for relative in re.findall(r'@import "([^"]+)"', styles)
    )

    assert "所在地" in main_js
    assert "provinceTabs" in main_js
    assert "cityTabs" in main_js
    assert "districtTabs" in main_js
    assert "regionTabs" not in main_js
    assert "buildRegionTree" in main_js
    assert "aggregateRegionStatus" in main_js
    assert "renderProvinceTabs" in main_js
    assert "renderCityTabs" in main_js
    assert "renderDistrictTabs" in main_js
    assert "selectedProvince" in main_js
    assert "selectedCity" in main_js
    assert "selectedLocationCode" in main_js
    assert "loadRegions" in main_js
    assert "/api/collection/regions" in main_js
    assert "/api/collection/region/reset_links" in main_js
    assert "resetRegionLinks" in main_js
    assert "重置本地区链接采集" in main_js
    assert 'state.stage === "links"' in main_js
    assert "location_code=" in main_js
    assert "全部省份" in main_js
    assert "全部城市" in main_js
    assert "全部地区" in main_js
    assert "请先选择省份" in main_js
    assert "请先选择城市" in main_js
    assert "aggregateRegionStatus" in main_js
    assert "region.status_label" in main_js
    assert "region-panel" in styles
    assert "region-level" in styles
    assert "region-level-title" in styles
    assert "region-tab" in styles
    assert "region-status" in styles


def test_collector_desktop_readme_documents_api_dependency_and_commands() -> None:
    readme = (APP_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Rust + Tauri" in readme
    assert "FAPAI_COLLECTOR_API_BASE" in readme
    assert "crow-desktop.runtime.json" in readme
    assert "npm run tauri:dev" in readme
    assert "npm run tauri:build" in readme
    assert "AI 再分析" in readme
    assert "手动更新" in readme
    assert "写入数据库" in readme


def test_collector_desktop_local_deploy_script_builds_to_temp_and_copies_local_runtime_bundle() -> None:
    script = REPO_ROOT.joinpath("scripts", "deploy-collector-desktop-local.ps1").read_text(encoding="utf-8")

    assert "FapaiFangCollectorDesktop" in script
    assert "LOCALAPPDATA" in script
    assert "fapaifang_collector_desktop.exe" in script
    assert "npm run tauri:build" in script
    assert "CARGO_TARGET_DIR" in script
    assert "pushd" in script
    assert "open-remote-auth-browser.ps1" in script
    assert "start-pc1-manual-auth-session.ps1" in script
    assert "start-pc1-auth-bridge.ps1" in script
    assert "start-taobao-cdp-browser.ps1" in script
    assert "export-taobao-cookie-snapshot.ps1" in script
    assert "browserless_seed_probe.py" in script
    assert "taobao_login_health.py" in script
    assert "internal_api_http.py" in script
    assert "start-fapaifang-collector.ps1" in script
    assert "FAPAI_REMOTE_AUTH_HOST" in script
    assert "FAPAI_REMOTE_AUTH_KEY_PATH" in script
    assert "[AllowEmptyString()][string]$RemotePasswordValue" in script
    assert "[AllowEmptyString()][string]$RemoteKeyPath" in script
    assert "RemoteAuthKeyPath" in script
    assert "id_ed25519" in script
    assert "id_rsa" in script
    assert "Stop-Process" in script
    assert "Start-Process" in script
    assert "update-collector-desktop-shortcut.ps1" in script
    assert "-ExpectedSha256 (Get-FileHash" in script
    assert '[string]$DataRoot = ""' in script
    assert '$previousEnvironment.FAPAI_DATA_ROOT_HOST' in script
    assert "CROW_AUTH_BROWSER_PROFILE_DIR' -Environment $savedEnvironment -PathValue" in script
    shortcut = REPO_ROOT.joinpath("scripts", "update-collector-desktop-shortcut.ps1").read_text(encoding="utf-8")
    assert "CreateShortcut" in shortcut
    assert "WScript.Shell" in shortcut
    assert "Crow.lnk" in shortcut
    assert "backup" in script.lower()
    assert "cmd /d /c" in script
    assert "Push-Location $env:SystemRoot" in script
    assert "& cmd /c $installCommand" not in script
    assert "& cmd /c $buildCommand" not in script


def test_remote_auth_browser_helper_can_use_ssh_key_without_password() -> None:
    script = REPO_ROOT.joinpath("scripts", "open-remote-auth-browser.ps1").read_text(encoding="utf-8")

    assert "Get-CrowEnvironmentValue -Name 'CROW_REMOTE_AUTH_KEY_PATH'" in script
    assert "key_filename" in script
    assert "\"allow_agent\": True" in script
    assert "\"look_for_keys\": True" in script
    assert "if (-not $resolvedRemotePassword -and -not $resolvedRemoteKeyPath)" in script
    assert "local-bridge" in script
    assert "watch-pc1-auth-auto-resume.ps1" in script
    assert "Start-LocalAuthAutoResumeWatcher" in script


def test_pc1_auth_bridge_uses_private_reverse_tunnel_and_human_browser_mode() -> None:
    script = REPO_ROOT.joinpath("scripts", "start-pc1-auth-bridge.ps1").read_text(encoding="utf-8")

    assert "HumanAuthMode" in script
    assert "Get-CdpEndpointProbe" in script
    assert "127.0.0.1:{0}:127.0.0.1:{1}" in script
    assert '"ExitOnForwardFailure=yes"' in script
    assert '"ServerAliveInterval=15"' in script
    assert "CROW_AUTH_BROWSER_PROFILE_DIR" in script
    assert "CROW_AUTH_BROWSER_PATH" in script
    assert "report_cdp_endpoint" in script
    assert "report_cdp_websocket_url" in script
    assert "webSocketDebuggerUrl" in script
    assert "loopback_websocket_url" in script
    assert "remote_websocket_mismatch" in script
    assert "$request.Proxy = $null" in script
    assert "ConvertTo-Json" in script
    assert "if ($SkipBrowserStart)" in script
    assert "& powershell.exe" in script
    assert "-StartUrl $StartUrl" in script
    assert "-ForceNew" not in script


def test_collector_desktop_local_deploy_script_bundles_pc1_auth_auto_resume_watcher() -> None:
    script = REPO_ROOT.joinpath("scripts", "deploy-collector-desktop-local.ps1").read_text(encoding="utf-8")

    assert "scripts\\watch-pc1-auth-auto-resume.ps1" in script


def test_collector_desktop_bundles_pc1_analysis_proxy_bridge() -> None:
    deploy_script = REPO_ROOT.joinpath("scripts", "deploy-collector-desktop-local.ps1").read_text(encoding="utf-8")
    readme = (APP_ROOT / "README.md").read_text(encoding="utf-8")

    assert "start-pc1-analysis-proxy-bridge.ps1" in deploy_script
    assert "register-pc1-analysis-proxy-bridge-task.ps1" in deploy_script
    assert "start-pc1-analysis-proxy-bridge.ps1" in readme

def test_collector_desktop_readme_documents_local_deploy_workflow() -> None:
    readme = (APP_ROOT / "README.md").read_text(encoding="utf-8")

    assert "deploy-collector-desktop-local.ps1" in readme
    assert "FapaiFangCollectorDesktop" in readme
    assert "start-fapaifang-collector.ps1" in readme
    assert "open-remote-auth-browser.ps1" in readme
    assert "export-taobao-cookie-snapshot.ps1" in readme


def test_collector_desktop_gitignore_keeps_source_and_drops_generated_artifacts() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "!collector-desktop/index.html" in gitignore
    assert "collector-desktop/src-tauri/gen/" in gitignore
    assert "node_modules/" in gitignore
    assert "dist/" in gitignore
    assert "target/" in gitignore
