"""Exercise persistence compatibility and default-path entry points offline."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.project_data_paths import resolve_project_data_root
from src.storage.repository_context import (
    _resolve_from_shared_artifact_roots,
    _shared_artifact_relative_path,
)
from tools import (
    backfill_archived_details,
    fetch_missing_detail_archives,
    prepare_recent_detail_replay,
)
from tools.run_isolated_collection_api import build_runtime_config

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["FPFData", "CrowData", "fPfDaTa", "cRoWdAtA"])
@pytest.mark.parametrize(
    "prefix", ["C:/repo/", "//server/share/", "\\\\server\\share\\"]
)
def test_persisted_artifact_paths_support_both_names(
    tmp_path, monkeypatch, name, prefix
):
    relative = "output/nodes/pc2/item/final.json"
    artifact = tmp_path / relative
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"sentinel":"unchanged"}', encoding="utf-8")
    monkeypatch.setenv("FAPAI_SHARED_ARTIFACT_ROOT", str(tmp_path))
    stored = prefix + name + "/" + relative
    assert _shared_artifact_relative_path(stored) == relative
    assert _resolve_from_shared_artifact_roots(stored) == str(artifact)
    assert artifact.read_bytes() == b'{"sentinel":"unchanged"}'


@pytest.mark.parametrize("name", ["FPFData", "CrowData"])
def test_persisted_path_traversal_remains_rejected(name):
    for tail in ["../secret", "output/../../secret", "./secret", "output/../secret"]:
        assert _shared_artifact_relative_path(f"//host/share/{name}/{tail}") is None
    assert _shared_artifact_relative_path(f"//host/share/{name}/") is None


@pytest.mark.parametrize(
    "module",
    [
        backfill_archived_details,
        fetch_missing_detail_archives,
        prepare_recent_detail_replay,
    ],
)
def test_maintenance_cli_preserves_old_data_and_explicit_override(
    tmp_path, monkeypatch, module
):
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    for key in ("FAPAI_DATA_ROOT", "FAPAI_DATA_ROOT_HOST", "CROW_DATA_ROOT_HOST"):
        monkeypatch.delenv(key, raising=False)
    old = tmp_path / "FPFData/datas"
    old.mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", [module.__name__])
    assert module.parse_args().data_root == old
    (tmp_path / "CrowData/datas").mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", [module.__name__, "--data-root", str(old)])
    assert module.parse_args().data_root == old


def test_isolated_api_and_rollback_keep_explicit_root(tmp_path, monkeypatch):
    monkeypatch.delenv("FAPAI_DATA_ROOT_HOST", raising=False)
    monkeypatch.delenv("CROW_DATA_ROOT_HOST", raising=False)
    old = tmp_path / "FPFData/datas"
    old.mkdir(parents=True)
    assert build_runtime_config(tmp_path, port=8011)["data_dir"] == old
    new = tmp_path / "CrowData/datas"
    new.mkdir(parents=True)
    assert build_runtime_config(tmp_path, port=8011, data_root=old)["data_dir"] == old
    monkeypatch.setenv("FAPAI_DATA_ROOT_HOST", str(new.parent))
    assert resolve_project_data_root(tmp_path) == new.parent
    monkeypatch.setenv("FAPAI_DATA_ROOT_HOST", str(old.parent))
    assert resolve_project_data_root(tmp_path) == old.parent
    assert new.is_dir() and old.is_dir()


def test_all_powershell_entrypoints_parse_without_execution():
    shell = (
        os.getenv("CROW_TEST_POWERSHELL")
        or shutil.which("pwsh")
        or shutil.which("powershell")
    )
    if not shell:
        pytest.skip("PowerShell unavailable")
    script = r"""
$ErrorActionPreference = 'Stop'
$errorsFound = @()
foreach ($file in Get-ChildItem -LiteralPath $env:CROW_TEST_SCRIPTS -Filter '*.ps1' -Recurse) {
  $tokens = $null; $parseErrors = $null
  $null = [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors)
  if ($parseErrors) { $errorsFound += $parseErrors }
}
if ($errorsFound.Count) { $errorsFound | ForEach-Object { Write-Output $_ }; exit 1 }
"""
    result = subprocess.run(
        [shell, "-NoProfile", "-Command", script],
        env=dict(os.environ, CROW_TEST_SCRIPTS=str(ROOT / "scripts")),
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_both_runtime_roots_are_ignored_by_git_and_docker():
    candidates = [
        f"{root}/secrets/probe.token"
        for root in ("FPFData", "CrowData", "fpfdata", "crowdata")
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z"],
        input=b"\0".join(path.encode("utf-8") for path in candidates) + b"\0",
        capture_output=True,
        cwd=ROOT,
        check=True,
    )
    assert result.stdout.split(b"\0") == [
        path.encode("utf-8") for path in candidates
    ] + [b""]
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "[Cc][Rr][Oo][Ww][Dd][Aa][Tt][Aa]/" in ignore
    assert "[Ff][Pp][Ff][Dd][Aa][Tt][Aa]/" in ignore


@pytest.mark.parametrize("data_name", ["custom-archive", "datas"])
def test_cookie_snapshot_legacy_root_with_special_data_directory(tmp_path, data_name):
    from src.auth_cookie_paths import AuthCookiePaths

    old = tmp_path / "FPFData"
    snapshot = old / "secrets/nodes/pc2/taobao-cookies.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("sentinel", encoding="utf-8")
    configured_data = old / data_name
    configured_data.mkdir()
    paths = AuthCookiePaths(
        env={}.get,
        repo_root=lambda: tmp_path,
        data_dir=lambda: str(configured_data),
        normalize_node=str,
        roots=lambda: [],
    )
    candidates = paths._auth_cookie_snapshot_root_candidates()
    assert candidates == [old]
    reader = AuthCookiePaths(
        env={}.get,
        repo_root=lambda: tmp_path,
        data_dir=lambda: str(configured_data),
        normalize_node=str,
        roots=lambda: candidates,
    )
    assert reader._resolve_auth_cookie_snapshot_path({"node_id": "pc2"}) == str(
        snapshot
    )
    assert snapshot.read_bytes() == b"sentinel"
    assert not (tmp_path / "CrowData").exists()


def test_explicit_cookie_root_bypasses_unrelated_root_ambiguity(tmp_path):
    from src.auth_cookie_paths import AuthCookiePaths

    for name in ("FPFData", "CrowData"):
        (tmp_path / name / "runtime").mkdir(parents=True)
    chosen = tmp_path / "explicit-cookie-root"
    env = {"FAPAI_COOKIE_SNAPSHOT_ROOT": str(chosen)}
    paths = AuthCookiePaths(
        env=env.get,
        repo_root=lambda: tmp_path,
        data_dir=lambda: str(tmp_path / "custom-archive"),
        normalize_node=str,
        roots=lambda: [],
    )
    assert paths._auth_cookie_snapshot_root_candidates() == [chosen]
