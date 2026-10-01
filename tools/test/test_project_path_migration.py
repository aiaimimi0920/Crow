from __future__ import annotations

from pathlib import Path

import pytest

import analyze_progress
import fix_original_urls
from tools.test.powershell_script_test_support import read_powershell_script_tree


REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_DATA_ROOTS = (
    r"C:\Users\Public\nas_home\AI\FPFData",
    r"Z:\project\project\FPFData",
)


def test_root_level_data_tools_resolve_paths_from_the_checkout() -> None:
    assert analyze_progress.REPO_ROOT == REPO_ROOT
    assert analyze_progress.DATA_DIR == REPO_ROOT / "datas" / "archive"
    assert fix_original_urls.REPO_ROOT == REPO_ROOT
    assert fix_original_urls.DATA_DIR == REPO_ROOT / "datas" / "archive"


def test_project_local_fpfdata_policy_keeps_runtime_contents_out_of_git() -> None:
    ignore = (REPO_ROOT / "FPFData" / ".gitignore").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "FPFData" / "README.md").read_text(encoding="utf-8")

    assert ignore.splitlines() == ["*", "!.gitignore", "!README.md"]
    assert "secrets" in readme
    assert "browser profiles" in readme
    assert "live PostgreSQL data" in readme
    assert "never mirrors deletions" in " ".join(readme.split())


def test_legacy_import_is_archive_only_and_non_destructive() -> None:
    script = (REPO_ROOT / "scripts" / "import-legacy-fpfdata.ps1").read_text(encoding="utf-8")

    for relative_path in ("backups", "datas", "jobs", "output", "postgres\\backups"):
        assert f'"{relative_path}"' in script
    assert "/XJ" in script
    assert '"/XD"' in script
    assert '"/XF"' in script
    assert "/MIR" not in script
    assert "Remove-Item" not in script
    assert '"secrets"' in script
    assert '"runtime"' in script
    assert '"live_postgres_data"' in script
    assert '"docker.local.env*"' in script
    assert '"*cookie*"' in script
    assert '"*credential*"' in script
    assert '"*token*"' in script


def test_local_operator_scripts_do_not_embed_legacy_data_roots() -> None:
    relative_default_scripts = (
        "backup-postgres-to-host.ps1",
        "check-postgres-backup-health.ps1",
        "collect-taobao-sf-locations.ps1",
        "complete-pc1-inplace-auth.ps1",
        "deploy-collector-desktop-local.ps1",
        "export-taobao-cookie-snapshot.ps1",
        "generate-all-seed-jobs.ps1",
        "register-continuous-collection-task.ps1",
        "register-fpfdata-sync-task.ps1",
        "register-pc1-nas-auth-recovery-task.ps1",
        "register-pc1-shared-auth-maintenance.ps1",
        "register-postgres-backup-health-task.ps1",
        "register-postgres-backup-task.ps1",
        "register-taobao-login-recovery-monitor-task.ps1",
        "register-taobao-login-watchdog-task.ps1",
        "start-continuous-collection.ps1",
        "start-detail-analysis-only.ps1",
        "start-pc1-auth-bridge.ps1",
        "start-pc1-manual-auth-session.ps1",
        "start-seed-scan-only.ps1",
        "start-taobao-cdp-browser.ps1",
        "sync-worker-artifacts-to-nas.ps1",
        "sync-docker-data-to-host.ps1",
        "trigger-taobao-login-recovery-if-needed.ps1",
        "watch-pc1-auth-auto-resume.ps1",
        "watch-pc1-nas-auth-recovery.ps1",
    )

    for name in relative_default_scripts:
        text = read_powershell_script_tree(REPO_ROOT / "scripts" / name)
        assert "PSScriptRoot" in text, name
        assert "FPFData" in text, name
        for legacy_root in LEGACY_DATA_ROOTS:
            assert legacy_root not in text, name


def test_powershell_script_tree_rejects_missing_dot_sourced_module(tmp_path: Path) -> None:
    entry_path = tmp_path / "entry.ps1"
    entry_path.write_text(
        '$moduleRoot = Join-Path $PSScriptRoot "entry"\n'
        '. (Join-Path $moduleRoot "missing.ps1")\n',
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="missing.ps1"):
        read_powershell_script_tree(entry_path)


def test_repository_rules_protect_live_pc2_and_nas() -> None:
    rules = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "Preserve runtime" in rules
    assert "database contents" in rules
    assert "A specific user instruction to defer deployment takes precedence" in rules
