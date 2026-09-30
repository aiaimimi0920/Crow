"""Load only shared helpers and extracted file-writing blocks in temporary bundles."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("layout", ["checkout", "flat"])
@pytest.mark.parametrize(
    "writer", ["apply-cookie-only-worker-env.ps1", "apply-worker-concurrency-env.ps1"]
)
def test_operator_bundle_aliases_and_writer_keep_unrelated_settings(
    tmp_path, layout, writer
):
    shell = (
        os.environ.get("CROW_TEST_POWERSHELL")
        or shutil.which("pwsh")
        or shutil.which("powershell")
    )
    if not shell:
        pytest.skip("PowerShell unavailable")
    ops = tmp_path / "ops/pc2-host" if layout == "checkout" else tmp_path / "ops"
    helpers = tmp_path / "scripts" if layout == "checkout" else ops / "runtime"
    ops.mkdir(parents=True)
    helpers.mkdir(parents=True)
    shutil.copy2(ROOT / "ops/pc2-host/crow-environment.ps1", ops)
    for name in ("project-environment.ps1", "compose-environment-file.ps1"):
        shutil.copy2(ROOT / "scripts" / name, helpers)
    source = (ROOT / "ops/pc2-host" / writer).read_text()
    # Exclude loader, network mounting, runtime validation and all installer bodies.
    block = source[
        source.index("$required = [ordered]@") : source.index("[pscustomobject]@")
    ]
    config = tmp_path / "synthetic.env"
    config.write_text(
        "# keep\nUNRELATED='literal-value'\nFAPAI_HOST_DETAIL_WORKER_COUNT=3\n"
    )
    script = tmp_path / "fixture.ps1"
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    script.write_text(
        "$ErrorActionPreference='Stop'\n. "
        + quote(ops / "crow-environment.ps1")
        + "\n"
        + "$EnvFile="
        + quote(config)
        + "\n$SnapshotPath='synthetic-snapshot'\n$DetailWorkerCount=4\n$AnalysisWorkerCount=4\n"
        + block
        + "\n[IO.File]::ReadAllLines($EnvFile) | ConvertTo-Json -Compress\n"
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-File", str(script)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = json.loads(result.stdout)
    assert "# keep" in lines and "UNRELATED='literal-value'" in lines
    values = dict(line.split("=", 1) for line in lines if "=" in line)
    assert (
        values["CROW_HOST_DETAIL_WORKER_COUNT"]
        == values["FAPAI_HOST_DETAIL_WORKER_COUNT"]
        == "4"
    )
    for name, value in values.items():
        if name.startswith("CROW_"):
            assert values["FAPAI_" + name[5:]] == value


def test_both_installers_include_shared_helpers_in_backup_copy_and_rollback_list():
    for name in ("install-cookie-only-runtime.ps1", "install-concurrency-runtime.ps1"):
        source = (ROOT / "ops/pc2-host" / name).read_text()
        manifest = source.split("$files = @(", 1)[1].split(")", 1)[0]
        for entry in (
            "crow-environment.ps1",
            "runtime\\project-environment.ps1",
            "runtime\\compose-environment-file.ps1",
        ):
            assert repr(entry).replace("\\\\", "\\") in manifest
        assert source.count("foreach ($name in $files)") >= 3


def test_installer_manifests_cover_versioned_environment_consumers():
    import re

    ops = ROOT / "ops/pc2-host"
    consumers = {
        path.relative_to(ops).as_posix().replace("/", "\\")
        for path in ops.rglob("*.ps1")
        if "Get-CrowEnvironmentValue" in path.read_text()
        or "Set-CrowEnvironmentValue" in path.read_text()
    }
    consumers.discard("crow-environment.ps1")
    for name in ("install-cookie-only-runtime.ps1", "install-concurrency-runtime.ps1"):
        source = (ops / name).read_text()
        manifest = source.split("$files = @(", 1)[1].split(")", 1)[0]
        entries = set(re.findall("'([^']+)'", manifest))
        assert consumers <= entries
