"""Execute only the pure operator environment helpers with synthetic inputs."""

import json
from pathlib import Path

import pytest

from tools.test import powershell_fixtures

crow_powershell_batch = powershell_fixtures.crow_powershell_batch

ROOT = Path(__file__).resolve().parents[2]


def _run(tmp_path, body, crow_powershell_batch):
    shell = crow_powershell_batch.shell
    helper = str(ROOT / "ops/pc2-host/crow-environment.ps1").replace("'", "''")
    script = tmp_path / "helper-only.ps1"
    script.write_text("$ErrorActionPreference='Stop'\n. '" + helper + "'\n" + body)
    result = crow_powershell_batch(
        [shell, "-NoProfile", "-File", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "crow", "fapai"])
def test_file_alias_group_overrides_process_group_without_changing_file(
    tmp_path, prefix, crow_powershell_batch
):
    path = tmp_path / "synthetic.env"
    raw = f"# fixture\n{prefix}_FIXTURE_VALUE=file-value\nSTANDARD_FIXTURE=keep\n"
    path.write_text(raw)
    data = _run(
        tmp_path,
        r"""
$env:CROW_FIXTURE_VALUE='process-new'
$env:FAPAI_FIXTURE_VALUE='process-old'
$read = Read-CrowOperatorEnvironment -Path 'synthetic.env'
$before=$env:CROW_FIXTURE_VALUE
Import-CrowOperatorEnvironment -Path 'synthetic.env'
@{before=$before;new=$env:CROW_FIXTURE_VALUE;old=$env:FAPAI_FIXTURE_VALUE;standard=$env:STANDARD_FIXTURE} | ConvertTo-Json -Compress
""",
        crow_powershell_batch,
    )
    assert data == {
        "before": "process-new",
        "new": "file-value",
        "old": "file-value",
        "standard": "keep",
    }
    assert path.read_text() == raw


def test_conflicting_file_is_validated_before_any_process_write(
    tmp_path, crow_powershell_batch
):
    (tmp_path / "synthetic.env").write_text(
        "FAPAI_FIXTURE_OTHER=changed\nCROW_FIXTURE_VALUE=private-new\nFAPAI_FIXTURE_VALUE=private-old\n"
    )
    data = _run(
        tmp_path,
        r"""
$env:CROW_FIXTURE_OTHER='before'
$env:FAPAI_FIXTURE_OTHER='before'
$errorText=''
try { Import-CrowOperatorEnvironment -Path 'synthetic.env' }
catch { $errorText=$_.Exception.Message }
@{error=$errorText;new=$env:CROW_FIXTURE_OTHER;old=$env:FAPAI_FIXTURE_OTHER} | ConvertTo-Json -Compress
""",
        crow_powershell_batch,
    )
    assert data["new"] == data["old"] == "before"
    assert (
        "CROW_FIXTURE_VALUE" in data["error"] and "FAPAI_FIXTURE_VALUE" in data["error"]
    )
    assert "private" not in data["error"]


def test_extracted_worker_count_respects_explicit_parameter_and_alias_conflict(
    tmp_path,
    crow_powershell_batch,
):
    source = str(
        ROOT / "ops/pc2-host/launch-host-direct-workers/worker-specs.ps1"
    ).replace("'", "''")
    data = _run(
        tmp_path,
        "$source='"
        + source
        + "'\n"
        + r"""
$t=$null;$e=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$t,[ref]$e)
$function=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Resolve-WorkerCount'},$true)
. ([scriptblock]::Create($function.Extent.Text))
$env:CROW_HOST_DETAIL_WORKER_COUNT='4'
$env:FAPAI_HOST_DETAIL_WORKER_COUNT='4'
$equal=Resolve-WorkerCount -RequestedCount 0 -EnvironmentName CROW_HOST_DETAIL_WORKER_COUNT -DefaultCount 3
$env:FAPAI_HOST_DETAIL_WORKER_COUNT='5'
$explicit=Resolve-WorkerCount -RequestedCount 6 -EnvironmentName CROW_HOST_DETAIL_WORKER_COUNT -DefaultCount 3
$errorText=''
try { Resolve-WorkerCount -RequestedCount 0 -EnvironmentName CROW_HOST_DETAIL_WORKER_COUNT -DefaultCount 3 | Out-Null }
catch { $errorText=$_.Exception.Message }
@{equal=$equal;explicit=$explicit;error=$errorText} | ConvertTo-Json -Compress
""",
        crow_powershell_batch,
    )
    assert data["equal"] == 4 and data["explicit"] == 6
    assert "Conflicting environment aliases" in data["error"]
