from __future__ import annotations

from tools.test.continuous_collection_scripts_test_context import *


def test_pc2_host_open_auth_latest_force_restarts_visible_browser_for_manual_auth() -> None:
    script = _pc2_host_script("open-auth-latest.ps1")

    assert "& powershell" in script
    assert "-StartMinimized" not in script
    assert "-EnsureOnly" not in script
    assert "-ForceNew" in script
    assert "-TerminateAllBrowserProcesses" in script


def test_pc2_host_open_auth_latest_avoids_system_web_in_interactive_task() -> None:
    script = _pc2_host_script("open-auth-latest.ps1")

    assert "Add-Type -AssemblyName System.Web" not in script
    assert "[System.Web.HttpUtility]" not in script
    assert "function ConvertFrom-AuthQueryString" in script
    assert "[System.Uri]::UnescapeDataString" in script
    assert "[System.Uri]::EscapeDataString" in script


def test_pc2_host_auth_trigger_runs_open_auth_in_interactive_hidden_task() -> None:
    script = _pc2_host_script("trigger-open-auth-task.ps1")

    assert "open-auth-latest.ps1" in script
    assert "FapaiPc2OpenAuth" in script
    assert "New-ScheduledTaskAction" in script
    assert "'-WindowStyle', 'Hidden'" in script
    assert "'-RequestedUrl'" in script
    assert "New-ScheduledTaskPrincipal" in script
    assert "-LogonType Interactive" in script
    assert "-RunLevel Limited" in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "Stop-ScheduledTask" in script
    assert "Register-ScheduledTask" in script
    assert "Start-ScheduledTask" in script


def test_solver_force_retry_monitor_prioritizes_seed_targets_and_throttles_detail_targets() -> None:
    script = REPO_ROOT.joinpath(".codex-temp", "bridge-control", "solver-force-retry-monitor.ps1").read_text(encoding="utf-8")

    assert "$seedCooldownSeconds = 60" in script
    assert "$detailCooldownSeconds = 300" in script
    assert "$seedSummaryPath =" in script
    assert "$seedRetryTargetUrl = 'https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1'" in script
    assert "function Get-SolverTargetScope" in script
    assert "function Test-SeedStageHasRemainingWork" in script
    assert "function Resolve-PreferredSolverTargetUrl" in script
    assert "function Test-SeedSummaryCdpUnreachable" in script
    assert "seed_summary=cdp_unreachable" in script
    assert "'sf-item.taobao.com'" in script
    assert "'sf.taobao.com/list/'" in script
    assert "$allowTargetChangeBypass = $targetScope -eq 'seed'" in script


def test_start_seed_scan_only_starts_seed_pool_without_detail_workers() -> None:
    script = _script("start-seed-scan-only.ps1")

    assert "generate-all-seed-jobs.ps1" in script
    assert "taobao-login-watchdog.ps1" in script
    assert "docker compose" in script
    assert "fapaifang-seed-collector" in script
    assert "fapaifang-seed-collector-6" in script
    assert "fapaifang-detail-worker" in script
    assert "stop" in script
    assert "docker update" in script
    assert "--restart=no" in script
    assert "CROW_SEED_PAGES_PER_RUN" in script
    assert "CROW_SEED_LOOP_INTERVAL_SECONDS=60" in script
    assert "CROW_SEED_PARALLEL_SORTS=1" in script
    assert "CROW_SEED_FAILURE_COOLDOWN_THRESHOLD=10" in script
    assert "CROW_SEED_FAILURE_COOLDOWN_SECONDS=120" in script
    assert "CROW_LIST_HTTP_TIMEOUT_SECONDS=8" in script
    assert "CROW_LIST_BROWSER_FALLBACK=0" in script
    assert "CROW_DETAIL_WORKER_RESTART=no" in script
    assert "CROW_DETAIL_ANALYSIS_WORKER_RESTART=no" in script
    assert "CROW_DETAIL_ANALYSIS_WORKER_2_RESTART=no" in script
    assert "CROW_DETAIL_ANALYSIS_WORKER_3_RESTART=no" in script
    assert "--profile analysis" in script
    assert "Cookie snapshot export failed" in script
    assert "--remove-orphans" not in script
    assert "docker-compose.postgres" not in script


def test_start_detail_analysis_only_starts_detail_and_analysis_pools_without_seed_workers() -> None:
    script = _script("start-detail-analysis-only.ps1")

    assert "taobao-login-watchdog.ps1" in script
    assert "docker compose" in script
    assert "fapaifang-detail-worker" in script
    assert "fapaifang-detail-worker-3" in script
    assert "fapaifang-detail-analysis-worker" in script
    assert "fapaifang-detail-analysis-worker-3" in script
    assert "fapaifang-seed-collector" in script
    assert '"--profile", "analysis"' in script
    assert "stop" in script
    assert "docker update" in script
    assert "--restart=no" in script
    assert "CROW_SEED_COLLECTOR_RESTART=no" in script
    assert "CROW_DETAIL_TARGET_SUCCESS" in script
    assert "CROW_DETAIL_ANALYSIS_TARGET_SUCCESS" in script
    assert "CROW_DETAIL_ANALYSIS_WORKER_RESTART=unless-stopped" in script
    assert "CROW_DETAIL_ANALYSIS_WORKER_2_RESTART=unless-stopped" in script
    assert "CROW_DETAIL_ANALYSIS_WORKER_3_RESTART=unless-stopped" in script
    assert "Cookie snapshot export failed" in script
    assert "--remove-orphans" not in script
    assert "docker-compose.postgres" not in script


def test_check_taobao_login_health_script_uses_multi_sample_health_gate() -> None:
    script = _script("check-taobao-login-health.ps1")

    assert '[string[]]$SampleUrl' in script
    assert "200782003__1.htm" in script
    assert "--sample-url" in script
    assert "foreach ($url in $healthSampleUrls)" in script
    assert "--remove-orphans" not in script


def test_taobao_login_watchdog_force_restarts_browser_when_cdp_websocket_is_dead() -> None:
    script = _script("taobao-login-watchdog.ps1")

    assert '$initial.Status -eq "cdp_unreachable"' in script
    assert "-not $SkipBrowserStart" in script
    assert '"-ForceNew"' in script
    assert "CDP websocket is unreachable" in script


def test_readme_documents_continuous_collection_workflow() -> None:
    readme = REPO_ROOT.joinpath("README.md").read_text(encoding="utf-8")

    assert "start-continuous-collection.ps1" in readme
    assert "generate-all-seed-jobs.ps1" in readme
    assert "taobao-login-watchdog.ps1" in readme
    assert "trigger-taobao-login-recovery-if-needed.ps1" in readme
    assert "register-taobao-login-recovery-monitor-task.ps1" in readme
    assert "register-taobao-login-watchdog-task.ps1" in readme
    assert "register-continuous-collection-task.ps1" in readme
    assert "start-seed-scan-only.ps1" in readme
    assert "start-detail-analysis-only.ps1" in readme
    assert "FAPAI_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json" in readme
    assert "FAPAI_COOKIE_SNAPSHOT=/data/secrets/taobao-cookies.json" in readme
    assert "FAPAI_SEED_PARALLEL_SORTS=1" in readme
    assert "fapaifang-detail-analysis-worker" in readme
    assert "fapaifang-detail-analysis-worker-3" in readme
    assert "detail_analysis_worker_2" in readme
    assert "raw_detail_captured" in readme
    assert "FAPAI_SEED_RESCAN_INTERVAL_SECONDS=900" in readme
    assert "FAPAI_SEED_FAILURE_COOLDOWN_SECONDS=1800" in readme
    assert "FAPAI_DETAIL_FAILURE_COOLDOWN_SECONDS=1800" in readme
    assert "multi-sample" in readme
    assert "50025969" in readme
    assert "200782003" in readme
    assert "事件触发式人工验证恢复器" in readme
