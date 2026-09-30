"""Extract approved mapping/write blocks only; never invoke NAS import or backup."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mode", ["CROW", "FAPAI", "equal", "conflict"])
def test_analysis_import_aliases_preserve_allowlist_and_fail_before_write(
    tmp_path, mode
):
    shell = (
        os.environ.get("CROW_TEST_POWERSHELL")
        or shutil.which("pwsh")
        or shutil.which("powershell")
    )
    if not shell:
        pytest.skip("PowerShell unavailable")
    source = (ROOT / "ops/pc2-host/import-host-direct-analysis-env.ps1").read_text()
    allowed = source[
        source.index("$allowedNames = @(") : source.index(
            "if (-not (Test-Path -LiteralPath $loaderPath))"
        )
    ]
    parse = source[source.index("$updates = @{}") : source.index("$backupDir =")]
    write = source[
        source.index(
            "$lines = [System.Collections.Generic.List[string]]"
        ) : source.index("[pscustomobject]@")
    ]
    incoming = tmp_path / "source.env"
    rows = [
        "OPENAI_API_KEY=synthetic-fixture",
        "OPENAI_BASE_URL=https://example.invalid/api",
        "UNAPPROVED=must-not-copy",
    ]
    for prefix in [mode] if mode in ("CROW", "FAPAI") else ["CROW", "FAPAI"]:
        value = (
            "private-other"
            if mode == "conflict" and prefix == "FAPAI"
            else "http://127.0.0.1:1234"
        )
        rows.append(prefix + "_LLM_PROXY=" + value)
    incoming.write_text("\n".join(rows) + "\n")
    target = tmp_path / "target.env"
    original = "# preserve\nUNRELATED=keep\nFAPAI_LLM_HTTP_PROXY=stale\nCROW_LLM_HTTP_PROXY=stale\n"
    target.write_text(original)
    helper = str(ROOT / "ops/pc2-host/crow-environment.ps1").replace("'", "''")
    script = tmp_path / "mapping-only.ps1"
    script.write_text(
        "$ErrorActionPreference='Stop'\n. '"
        + helper
        + "'\n$resolvedSource='source.env'\n$envPath='target.env'\n"
        + allowed
        + "\ntry {\n"
        + parse
        + write
        + "\n@{ok=$true}|ConvertTo-Json -Compress\n} catch { @{ok=$false;error=$_.Exception.Message}|ConvertTo-Json -Compress }\n"
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-File", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    if mode == "conflict":
        assert status["ok"] is False and "private-other" not in status["error"]
        assert target.read_text() == original
    else:
        assert status == {"ok": True}
        final = target.read_text()
        assert "# preserve\nUNRELATED=keep\n" in final
        assert "UNAPPROVED" not in final and "LLM_HTTP_PROXY" not in final
        assert "CROW_LLM_PROXY=http://127.0.0.1:1234" in final
        assert "FAPAI_LLM_PROXY=http://127.0.0.1:1234" in final


def test_solver_cmd_pairs_explicit_settings_without_running_the_solver():
    import re

    source = (ROOT / "ops/pc2-host/start-pc2-local-solver.cmd").read_text()
    values = dict(
        re.findall(r'^set "((?:CROW|FAPAI)_[^=]+)=([^"\n]*)"$', source, re.MULTILINE)
    )
    assert values
    for key, value in values.items():
        if key.startswith("CROW_"):
            assert values["FAPAI_" + key[5:]] == value
    assert "%FAPAI_" not in source


def test_embedded_auth_process_reads_canonical_values_from_its_paired_producer():
    import ast

    source = (ROOT / "scripts/open-remote-auth-browser.ps1").read_text()
    snippet = source.split("$pythonCode = @'", 1)[1].split("'@", 1)[0]
    expected = {"host", "user", "password", "key_path", "command"}
    nodes = [
        node
        for node in ast.parse(snippet).body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in expected
    ]
    keys = {
        node.value
        for assignment in nodes
        for node in ast.walk(assignment)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("CROW_REMOTE_AUTH_")
    }
    assert len(nodes) == len(keys) == 5
    for key in keys:
        assert "Set-CrowEnvironmentValue -Name '" + key + "'" in source
    import sys

    script = "import os, json\n" + "\n".join(ast.unparse(node) for node in nodes)
    script += (
        "\nprint(json.dumps({key: globals()[key] for key in "
        + repr(sorted(expected))
        + "}))"
    )
    environment = {key: "synthetic-value" for key in keys}
    if "SystemRoot" in os.environ:
        environment["SystemRoot"] = os.environ["SystemRoot"]
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert set(json.loads(result.stdout).values()) == {"synthetic-value"}
