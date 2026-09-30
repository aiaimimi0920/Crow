"""Run pure Bash helpers only; no deployment or browser entrypoint is sourced."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.shell_environment_file import declared_names

ROOT = Path(__file__).resolve().parents[2]


def _run(body, environment, tmp_path):
    shell = shutil.which("bash")
    if not shell or os.name == "nt":
        pytest.skip("Native POSIX Bash required")
    process = {"PATH": os.environ["PATH"], **environment}
    return subprocess.run(
        [
            shell,
            "-c",
            'set -eu; source "$1"; ' + body,
            "fixture",
            str(ROOT / "scripts/project-environment.sh"),
            str(ROOT / "tools/shell_environment_file.py"),
        ],
        cwd=tmp_path,
        env=process,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize(
    "values,expected",
    [
        ({}, "default"),
        ({"CROW_TEST": ""}, "default"),
        ({"FAPAI_TEST": "old"}, "old"),
        ({"CROW_TEST": "new"}, "new"),
        ({"CROW_TEST": "equal", "FAPAI_TEST": "equal"}, "equal"),
    ],
)
def test_shell_alias_reads_retain_colon_default_semantics(tmp_path, values, expected):
    result = _run("crow_env CROW_TEST default", values, tmp_path)
    assert result.returncode == 0 and result.stdout == expected


def test_shell_conflict_uses_only_names_and_path_comparison_is_lexical(tmp_path):
    result = _run(
        "crow_env CROW_TEST",
        {"CROW_TEST": "private-a", "FAPAI_TEST": "private-b"},
        tmp_path,
    )
    assert result.returncode == 2 and "private" not in result.stderr
    assert "CROW_TEST" in result.stderr and "FAPAI_TEST" in result.stderr
    result = _run(
        "crow_env CROW_DATA_ROOT",
        {
            "CROW_DATA_ROOT": str(tmp_path / "data"),
            "FAPAI_DATA_ROOT": str(tmp_path) + "/./data/",
        },
        tmp_path,
    )
    assert result.returncode == 0 and result.stdout == str(tmp_path / "data")
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("file_name", ["CROW_TEST", "FAPAI_TEST"])
def test_declarative_file_group_overrides_process_even_when_same_value(
    tmp_path, file_name
):
    (tmp_path / "synthetic.env").write_text(file_name + "=file-value\n")
    values = {"CROW_TEST": "process-new", "FAPAI_TEST": "process-old"}
    values[file_name] = "file-value"
    result = _run(
        'crow_source_env_file synthetic.env "$2"; printf "%s|%s" "$CROW_TEST" "$FAPAI_TEST"',
        values,
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "file-value|file-value"


def test_file_conflict_and_dynamic_declarations_fail_without_value_disclosure(tmp_path):
    for content in [
        "CROW_TEST=private-a\nFAPAI_TEST=private-b\n",
        "if true; then CROW_TEST=private-a; fi\n",
        "CROW_TEST=$(printf private-a)\n",
        "unset CROW_TEST\n",
    ]:
        (tmp_path / "synthetic.env").write_text(content)
        result = _run('crow_source_env_file synthetic.env "$2"', {}, tmp_path)
        assert result.returncode != 0 and "private" not in result.stderr


def test_declared_subset_keeps_quotes_comments_and_simple_references():
    assert declared_names(
        "export CROW_TEST='literal $() ; value'\nFAPAI_TEST=\"${OTHER}\" # note\nOPENAI_MODEL=model\n"
    ) == ["CROW_TEST", "FAPAI_TEST"]
    for text in [
        "CROW_TEST=${OTHER:-x}",
        "CROW_TEST=one two",
        "CROW_TEST=x; true",
        "CROW_TEST=\\",
        "CROW_TEST='multiline",
        "IFS=x",
        "_crow_file=x",
    ]:
        with pytest.raises(ValueError):
            declared_names(text)


def test_flat_browser_helper_bundle_loads_and_conflicts_before_runtime_work(tmp_path):
    shutil.copy2(ROOT / "scripts/project-environment.sh", tmp_path)
    shutil.copy2(ROOT / "ops/pc2-linux/process-supervisor.sh", tmp_path)
    body = "source ./process-supervisor.sh; crow_validate_env; printf started"
    result = _run(body, {"CROW_TEST": "private-a", "FAPAI_TEST": "private-b"}, tmp_path)
    assert result.returncode == 2 and result.stdout == ""
    source = (ROOT / "ops/pc2-linux/start-browser-solver.sh").read_text()
    assert source.index("crow_validate_env") < source.index(
        'if [[ ! -r "$vnc_password_file"'
    )
    result = _run("crow_lexical_path /fixture/a/../b/", {}, tmp_path)
    assert result.returncode == 0 and result.stdout == "/fixture/b"


def test_quoted_literal_and_existing_allexport_mode_are_preserved(tmp_path):
    (tmp_path / "synthetic.env").write_text("CROW_TEST='literal $() ; value'\n")
    result = _run(
        'set -a; crow_source_env_file synthetic.env "$2"; [[ "$-" == *a* ]]; printf "%s" "$FAPAI_TEST"',
        {},
        tmp_path,
    )
    assert result.returncode == 0 and result.stdout == "literal $() ; value"
    for content in [
        "\ufeffCROW_TEST=private-value\n",
        "CROW_TEST=private-value\r\n",
        "CROW_TEST=private\x00value\n",
    ]:
        with pytest.raises(ValueError):
            declared_names(content)


@pytest.mark.parametrize(
    "invalid",
    [
        b"\xef\xbb\xbfCROW_TEST=private-value\n",
        b"CROW_TEST=private-value\r\n",
        b"CROW_TEST=private-value\r",
        b"CROW_TEST=private\x00value\n",
    ],
)
def test_cli_rejects_actual_control_bytes_before_sourcing_any_setting(
    tmp_path, invalid
):
    prefix = b"UNRELATED_FIXTURE=private-before\n"
    original = (
        invalid + prefix if invalid.startswith(b"\xef\xbb\xbf") else prefix + invalid
    )
    path = tmp_path / "synthetic.env"
    path.write_bytes(original)
    result = _run(
        'if crow_source_env_file synthetic.env "$2"; then exit 33; fi; printf "%s" "${UNRELATED_FIXTURE-unset}"',
        {},
        tmp_path,
    )
    assert result.returncode == 0 and result.stdout == "unset"
    assert "Unsupported declarative environment file" in result.stderr
    assert "private" not in result.stderr
    assert path.read_bytes() == original
