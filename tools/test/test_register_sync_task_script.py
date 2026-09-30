from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_register_sync_task_script_installs_periodic_windows_task() -> None:
    script = REPO_ROOT.joinpath("scripts", "register-fpfdata-sync-task.ps1").read_text(encoding="utf-8")

    assert "FapaiFangDataSync" in script
    assert "New-ScheduledTaskTrigger" in script
    assert "-RepetitionInterval" in script
    assert "sync-docker-data-to-host.ps1" in script
    assert "PSScriptRoot" in script
    assert 'Resolve-CrowProjectDataRoot' in script
    assert 'project-data-root.ps1' in script
    assert "Z:\\project\\project\\FPFData" not in script
    assert "Convert-DataRootForScheduledTask" in script
    assert "DisplayRoot" in script
    assert "GetFullPath" in script
    assert "-SkipPostgres" in script
    assert "Register-ScheduledTask" in script
