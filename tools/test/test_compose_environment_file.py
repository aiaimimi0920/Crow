"""Run only the scoped env-file writer against synthetic temporary files."""

import json
import os
from pathlib import Path

import pytest

from tools.test import powershell_fixtures

crow_powershell_batch = powershell_fixtures.crow_powershell_batch

ROOT = Path(__file__).resolve().parents[2]


def test_existing_values_and_explicit_pair_updates_are_preserved(
    tmp_path, crow_powershell_batch
):
    shell = crow_powershell_batch.shell
    config = tmp_path / "fixture.env"
    original = (
        b"# keep\nexport FAPAI_TEST = 'existing'\nKEEP_UNRELATED=synthetic-$value\n"
    )
    config.write_bytes(original)
    if os.name != "nt":
        config.chmod(0o600)
    script = tmp_path / "writer.ps1"
    helper = str(ROOT / "scripts/compose-environment-file.ps1").replace("'", "''")
    target = str(config).replace("'", "''")
    script.write_text(
        ". '"
        + helper
        + "'\n$path = '"
        + target
        + "'\n"
        + r"""
$ErrorActionPreference='Stop'
$before=[Convert]::ToBase64String([IO.File]::ReadAllBytes($path))
Set-CrowEnvironmentFileValue -Path $path -Key CROW_TEST -Value 'default' -OnlyIfMissing
$unchanged=$before -eq [Convert]::ToBase64String([IO.File]::ReadAllBytes($path))
Set-CrowEnvironmentFileValue -Path $path -Key CROW_TEST -Value 'requested'
$after=[IO.File]::ReadAllText($path)
$errors=@()
foreach($invalid in @('private # unsafe', 'private$VAR', "private`nunsafe")) {
    try { Set-CrowEnvironmentFileValue -Path $path -Key CROW_TEST -Value $invalid; $errors+='missing error' }
    catch { $errors+=$_.Exception.Message }
}
@{unchanged=$unchanged; after=$after; final=[IO.File]::ReadAllText($path); errors=$errors} | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    result = crow_powershell_batch(
        [shell, "-NoProfile", "-File", str(script)],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["unchanged"] is True
    assert data["after"] == data["final"]
    assert set(data["final"].splitlines()) == {
        "# keep",
        "export CROW_TEST=requested",
        "export FAPAI_TEST=requested",
        "KEEP_UNRELATED=synthetic-$value",
    }
    if os.name != "nt":
        assert config.stat().st_mode & 0o777 == 0o600
    assert len(data["errors"]) == 3
    assert all(
        "CROW_TEST" in error and "FAPAI_TEST" in error and "private" not in error
        for error in data["errors"]
    )


@pytest.mark.parametrize(
    "initial",
    ["CROW_TEST=existing\n", "FAPAI_TEST=\n", "CROW_TEST=one\nFAPAI_TEST=two\n"],
)
def test_ensure_keeps_any_existing_alias_bytes_unchanged(
    tmp_path, initial, crow_powershell_batch
):
    shell = crow_powershell_batch.shell
    path = tmp_path / "fixture.env"
    path.write_bytes(initial.encode())
    helper = str(ROOT / "scripts/compose-environment-file.ps1").replace("'", "''")
    target = str(path).replace("'", "''")
    result = crow_powershell_batch(
        [
            shell,
            "-NoProfile",
            "-Command",
            ". '"
            + helper
            + "'; Set-CrowEnvironmentFileValue -Path '"
            + target
            + "' -Key CROW_TEST -Value default -OnlyIfMissing",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert path.read_bytes() == initial.encode()


@pytest.mark.parametrize(
    "name",
    [
        "start-continuous-collection.ps1",
        "start-seed-scan-only.ps1",
        "start-detail-analysis-only.ps1",
    ],
)
def test_mode_script_writer_functions_delegate_without_running_the_mode(
    tmp_path, name, crow_powershell_batch
):
    shell = crow_powershell_batch.shell
    script = tmp_path / "functions-only.ps1"
    helper = str(ROOT / "scripts/compose-environment-file.ps1").replace("'", "''")
    source = str(ROOT / "scripts" / name).replace("'", "''")
    config = str(tmp_path / "fixture.env").replace("'", "''")
    script.write_text(
        ". '"
        + helper
        + "'\n$source = '"
        + source
        + "'\n$path = '"
        + config
        + "'\n"
        + r"""
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'source parse failed'}
$functions=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in @('Set-EnvLine','Ensure-EnvLine')},$true))
foreach($function in $functions){. ([scriptblock]::Create($function.Extent.Text))}
Set-EnvLine -Path $path -Key CROW_TEST -Value '7'
[IO.File]::ReadAllLines($path) | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    result = crow_powershell_batch(
        [shell, "-NoProfile", "-File", str(script)],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert set(json.loads(result.stdout)) == {"CROW_TEST=7", "FAPAI_TEST=7"}
    source_text = (ROOT / "scripts" / name).read_text()
    assert (
        "& docker compose" not in source_text
        and "& docker @composeArgs" not in source_text
    )
    assert "crow_compose.py" in source_text
    if name != "start-continuous-collection.ps1":
        startup = source_text.split("Push-Location $repoRoot", 1)[1]
        assert startup.index("--check") < startup.index(
            "Disable-DockerRestartPolicy -Services"
        )


def test_reused_host_restores_environment_directory_and_runspace(
    tmp_path, crow_powershell_batch
):
    def command(source):
        result = crow_powershell_batch(
            [crow_powershell_batch.shell, "-NoProfile", "-Command", source],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    snapshot = r"""
@{pid=$PID;path=$env:PATH;cwd=[Environment]::CurrentDirectory;
added=[Environment]::GetEnvironmentVariable('CROW_BATCH_ISOLATION');
variable=[bool](Get-Variable BatchIsolation -Scope Global -ErrorAction SilentlyContinue);
function=[bool](Get-Command BatchIsolation -ErrorAction SilentlyContinue)} | ConvertTo-Json -Compress
"""
    before = command(snapshot)
    changed = command(
        "$env:CROW_BATCH_ISOLATION='synthetic'; $env:PATH='modified'; "
        "$global:BatchIsolation='synthetic'; function global:BatchIsolation {} ; "
        "[Environment]::CurrentDirectory=[IO.Path]::GetTempPath(); " + snapshot
    )
    assert changed["pid"] == before["pid"]
    assert changed["added"] == "synthetic" and changed["path"] == "modified"
    assert changed["variable"] is True and changed["function"] is True
    assert command(snapshot) == before
    command("Remove-Item Env:PATH; " + snapshot)
    assert command(snapshot) == before
    failed = crow_powershell_batch(
        [
            crow_powershell_batch.shell,
            "-NoProfile",
            "-Command",
            "$env:CROW_BATCH_ISOLATION='failed-case'; throw 'synthetic failure'",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert failed.returncode != 0 and "synthetic failure" in failed.stderr
    assert command(snapshot) == before


@pytest.mark.parametrize("body", ["exit 7", "throw 'failure'", "Write-Error 'failure'"])
def test_shared_host_rejects_failure_and_survives(
    tmp_path, crow_powershell_batch, body
):
    def run(source):
        return crow_powershell_batch(
            [crow_powershell_batch.shell, "-NoProfile", "-Command", source],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    before = run("$PID")
    failed = run("$env:CROW_BATCH_FAILURE='synthetic'; " + body)
    assert failed.returncode != 0
    after = run("if($env:CROW_BATCH_FAILURE) { throw 'leaked' }; $PID")
    assert after.returncode == 0 and after.stdout == before.stdout


def test_shared_host_inherits_environment_per_request(
    tmp_path, crow_powershell_batch, monkeypatch
):
    def read():
        result = crow_powershell_batch(
            [
                crow_powershell_batch.shell,
                "-NoProfile",
                "-Command",
                "$env:CROW_BATCH_DYNAMIC",
            ],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0
        return result.stdout

    monkeypatch.setenv("CROW_BATCH_DYNAMIC", "first")
    assert read() == "first"
    monkeypatch.setenv("CROW_BATCH_DYNAMIC", "second")
    assert read() == "second"
    monkeypatch.delenv("CROW_BATCH_DYNAMIC")
    assert read() == ""


def test_shared_host_preserves_native_failure(tmp_path, crow_powershell_batch):
    import sys

    interpreter = sys.executable.replace("'", "''")
    result = crow_powershell_batch(
        [
            crow_powershell_batch.shell,
            "-NoProfile",
            "-Command",
            "& '" + interpreter + "' -c 'raise SystemExit(7)'",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 7
