from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT_PATH = Path("scripts/sync-worker-artifacts-to-nas.ps1").resolve()


def _powershell() -> str:
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell is not available")
    return executable


def test_worker_artifact_sync_script_syncs_only_critical_directories() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert '"output", "datas", "jobs", "secrets"' in script
    assert "robocopy" in script
    assert "/XJ" in script
    assert "chrome-cdp-profile" not in script
    assert "edge-cdp-profile" not in script
    assert "LoopIntervalSeconds" in script


def test_worker_artifact_sync_script_uses_checkout_relative_source_and_explicit_target() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "$PSScriptRoot" in script
    assert 'Resolve-CrowProjectDataRoot' in script
    assert 'project-data-root.ps1' in script
    assert "FAPAI_ARTIFACT_SYNC_TARGET_ROOT" in script
    assert r"C:\Users\Public\nas_home\AI\FPFData" not in script
    assert r"\\192.168.15.200\docker\fapaifang" not in script


def test_relative_source_root_is_resolved_from_checkout(tmp_path: Path) -> None:
    target = tmp_path / "target"
    result = subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-File",
            str(SCRIPT_PATH),
            "-SourceRoot",
            "FPFData",
            "-TargetRoot",
            str(target),
            "-IncludeDirs",
            "missing-test-directory",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert target.is_dir()


@pytest.mark.parametrize(
    ("arguments", "expected_error"),
    [
        (["-SourceRoot", "FPFData"], "TargetRoot is required"),
        (
            ["-SourceRoot", "FPFData", "-TargetRoot", "relative-target"],
            "TargetRoot must be an absolute local or UNC path",
        ),
    ],
)
def test_sync_rejects_missing_or_relative_target(
    tmp_path: Path,
    arguments: list[str],
    expected_error: str,
) -> None:
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-File", str(SCRIPT_PATH), *arguments],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not (tmp_path / "relative-target").exists()
