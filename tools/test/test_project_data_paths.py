"""Read-only root selection fixtures, shared with the PowerShell implementation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.project_data_paths import (
    resolve_collection_data_dir,
    resolve_project_data_root,
)

ROOT = Path(__file__).resolve().parents[2]


def fixture_cases(root: Path) -> list[dict]:
    cases = []
    definitions = [
        ("fresh", {}, {}, "", "CrowData"),
        (
            "shell",
            {"FPFData/README.md": "x", "FPFData/.gitignore": "x"},
            {},
            "",
            "CrowData",
        ),
        ("old", {"FPFData/secrets/token": "sentinel"}, {}, "", "FPFData"),
        ("new", {"CrowData/datas/a": "sentinel"}, {}, "", "CrowData"),
        (
            "old_new_shell",
            {"FPFData/datas/a": "old", "CrowData/README.md": "x"},
            {},
            "",
            "FPFData",
        ),
        ("both", {"FPFData/a": "old", "CrowData/a": "new"}, {}, "", None),
        (
            "explicit_both",
            {"FPFData/a": "old", "CrowData/a": "new"},
            {},
            "FPFData",
            "FPFData",
        ),
        ("mixed_case", {"fPfDaTa/a": "old"}, {}, "", "fPfDaTa"),
        ("case_conflict", {"CrowData/a": "one", "crowdata/a": "two"}, {}, "", None),
        (
            "legacy_env",
            {"CrowData/a": "new"},
            {"FAPAI_DATA_ROOT_HOST": "existing"},
            "",
            "existing",
        ),
        ("new_env", {}, {"CROW_DATA_ROOT_HOST": "new"}, "", "new"),
        (
            "conflict_env",
            {},
            {"CROW_DATA_ROOT_HOST": "new", "FAPAI_DATA_ROOT_HOST": "old"},
            "",
            None,
        ),
        (
            "same_env",
            {},
            {"CROW_DATA_ROOT_HOST": "same/../same", "FAPAI_DATA_ROOT_HOST": "same"},
            "",
            "same",
        ),
        (
            "explicit_env",
            {},
            {"CROW_DATA_ROOT_HOST": "new", "FAPAI_DATA_ROOT_HOST": "old"},
            "chosen",
            "chosen",
        ),
        ("file_env", {"docker.local.env": "FAPAI_DATA_ROOT_HOST=old\n"}, {}, "", "old"),
        ("file_new", {"docker.local.env": "CROW_DATA_ROOT_HOST=new\n"}, {}, "", "new"),
        (
            "file_conflict",
            {"docker.local.env": "CROW_DATA_ROOT_HOST=new\nFAPAI_DATA_ROOT_HOST=old\n"},
            {},
            "",
            None,
        ),
        (
            "process_over_file",
            {"docker.local.env": "FAPAI_DATA_ROOT_HOST=old\n"},
            {"CROW_DATA_ROOT_HOST": "process"},
            "",
            "process",
        ),
        (
            "file_duplicate",
            {"docker.local.env": "FAPAI_DATA_ROOT_HOST=a\nFAPAI_DATA_ROOT_HOST=b\n"},
            {},
            "",
            None,
        ),
        ("data_not_management", {}, {"FAPAI_DATA_ROOT": "datas-only"}, "", "CrowData"),
        ("root_file", {"FPFData": "not a directory"}, {}, "", None),
    ]
    definitions.extend(
        [
            (
                "file_quoted",
                {
                    "docker.local.env": ' FAPAI_DATA_ROOT_HOST = "Crow Data" # selected\n'
                },
                {},
                "",
                "Crow Data",
            ),
            (
                "file_single_quote",
                {"docker.local.env": "export CROW_DATA_ROOT_HOST='Crow Data'\n"},
                {},
                "",
                "Crow Data",
            ),
            (
                "file_comment",
                {"docker.local.env": "FAPAI_DATA_ROOT_HOST=old # note\n"},
                {},
                "",
                "old",
            ),
            (
                "file_bad_quote",
                {"docker.local.env": 'FAPAI_DATA_ROOT_HOST="unterminated\n'},
                {},
                "",
                None,
            ),
            (
                "file_interpolation",
                {"docker.local.env": "FAPAI_DATA_ROOT_HOST=${HOME}/data\n"},
                {},
                "",
                None,
            ),
            (
                "file_empty_duplicate",
                {
                    "docker.local.env": "FAPAI_DATA_ROOT_HOST=\nFAPAI_DATA_ROOT_HOST=other\n"
                },
                {},
                "",
                None,
            ),
            (
                "file_unicode",
                {"docker.local.env": 'CROW_DATA_ROOT_HOST="乌鸦 数据"\n'},
                {},
                "",
                "乌鸦 数据",
            ),
        ]
    )
    definitions.append(
        (
            "same_env_trailing_slash",
            {},
            {"CROW_DATA_ROOT_HOST": "same/", "FAPAI_DATA_ROOT_HOST": "same"},
            "",
            "same",
        )
    )
    definitions.append(
        (
            "file_bare_variable",
            {"docker.local.env": "FAPAI_DATA_ROOT_HOST=$HOME/data\n"},
            {},
            "",
            None,
        )
    )
    for name, files, env, explicit, expected in definitions:
        directory = root / name
        directory.mkdir()
        for relative, content in files.items():
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        if name == "case_conflict" and len(list(directory.iterdir())) != 2:
            continue  # Case-insensitive filesystems cannot represent this fixture.
        cases.append(
            dict(
                root=str(directory),
                env=env,
                explicit=explicit,
                expected=str(directory / expected) if expected else None,
            )
        )
    directory = root / "linked_old"
    directory.mkdir()
    target = directory / "target"
    target.mkdir()
    (target / "sentinel").write_text("unchanged", encoding="utf-8")
    link = directory / "FPFData"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name == "nt":
            junction = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
            )
            if junction.returncode:
                raise AssertionError(
                    "Cannot create temporary directory link/junction fixture"
                ) from None
        else:
            raise
    cases.extend(
        [
            dict(root=str(directory), env={}, explicit="", expected=str(link)),
            dict(
                root=str(directory),
                env={
                    "CROW_DATA_ROOT_HOST": str(link),
                    "FAPAI_DATA_ROOT_HOST": str(target),
                },
                explicit="",
                expected=None,
            ),
            dict(
                root=str(directory),
                env={
                    "CROW_DATA_ROOT_HOST": str(link),
                    "FAPAI_DATA_ROOT_HOST": str(target),
                },
                explicit=str(link),
                expected=str(link),
            ),
        ]
    )
    return cases


def snapshot(root: Path) -> dict:
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


def test_python_root_selection_is_read_only(tmp_path):
    cases = fixture_cases(tmp_path)
    before = snapshot(tmp_path)
    for case in cases:
        if case["expected"] is None:
            with pytest.raises((ValueError, OSError)):
                resolve_project_data_root(
                    case["root"], case["explicit"], env=case["env"]
                )
        else:
            assert (
                str(
                    resolve_project_data_root(
                        case["root"], case["explicit"], env=case["env"]
                    )
                )
                == case["expected"]
            )
    assert snapshot(tmp_path) == before


def test_powershell_root_selection_matches_python(tmp_path):
    shell = (
        os.getenv("CROW_TEST_POWERSHELL")
        or shutil.which("pwsh")
        or shutil.which("powershell")
    )
    if not shell:
        pytest.skip("PowerShell unavailable")
    cases = fixture_cases(tmp_path)
    input_path = tmp_path / "cases.json"
    input_path.write_text(json.dumps(cases), encoding="utf-8")
    before = snapshot(tmp_path)
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
. $env:CROW_TEST_RESOLVER
$results = @()
foreach ($case in (Get-Content -Raw -LiteralPath $env:CROW_TEST_CASES | ConvertFrom-Json)) {
  foreach ($key in @('CROW_DATA_ROOT_HOST', 'FAPAI_DATA_ROOT_HOST', 'FAPAI_DATA_ROOT')) { [Environment]::SetEnvironmentVariable($key, $null, 'Process') }
  foreach ($property in $case.env.PSObject.Properties) { [Environment]::SetEnvironmentVariable($property.Name, $property.Value, 'Process') }
  try { $results += (Resolve-CrowProjectDataRoot -RepoRoot $case.root -ExplicitRoot $case.explicit) }
  catch { $results += $null }
}
ConvertTo-Json -InputObject $results -Compress
"""
    env = dict(
        os.environ,
        CROW_TEST_RESOLVER=str(ROOT / "scripts/project-data-root.ps1"),
        CROW_TEST_CASES=str(input_path),
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-Command", script],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=40,
        check=True,
    )
    assert json.loads(result.stdout) == [case["expected"] for case in cases]
    assert snapshot(tmp_path) == before


def test_empty_subdirectory_preserves_old_installation(tmp_path):
    (tmp_path / "FPFData/datas").mkdir(parents=True)
    assert resolve_project_data_root(tmp_path, env={}) == tmp_path / "FPFData"


def test_explicit_collection_subdirectory_keeps_legacy_meaning(tmp_path, monkeypatch):
    monkeypatch.setenv("FAPAI_DATA_ROOT", str(tmp_path / "actual-datas"))
    monkeypatch.setenv("CROW_DATA_ROOT_HOST", str(tmp_path / "management"))
    assert resolve_collection_data_dir(tmp_path) == tmp_path / "actual-datas"
    assert (
        resolve_collection_data_dir(tmp_path, tmp_path / "explicit")
        == tmp_path / "explicit"
    )
