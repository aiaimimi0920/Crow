"""Run only the scoped env-file writer against synthetic temporary files."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_existing_values_and_explicit_pair_updates_are_preserved(tmp_path):
    shell = (
        os.environ.get("CROW_TEST_POWERSHELL")
        or shutil.which("pwsh")
        or shutil.which("powershell")
    )
    if not shell:
        pytest.skip("PowerShell unavailable")
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
    result = subprocess.run(
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
def test_ensure_keeps_any_existing_alias_bytes_unchanged(tmp_path, initial):
    shell = (
        os.environ.get("CROW_TEST_POWERSHELL")
        or shutil.which("pwsh")
        or shutil.which("powershell")
    )
    if not shell:
        pytest.skip("PowerShell unavailable")
    path = tmp_path / "fixture.env"
    path.write_bytes(initial.encode())
    helper = str(ROOT / "scripts/compose-environment-file.ps1").replace("'", "''")
    target = str(path).replace("'", "''")
    result = subprocess.run(
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
def test_mode_script_writer_functions_delegate_without_running_the_mode(tmp_path, name):
    shell = (
        os.environ.get("CROW_TEST_POWERSHELL")
        or shutil.which("pwsh")
        or shutil.which("powershell")
    )
    if not shell:
        pytest.skip("PowerShell unavailable")
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
    result = subprocess.run(
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
