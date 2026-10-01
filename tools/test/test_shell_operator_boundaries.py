"""Exercise helper inputs and an extracted rollback against a fake Docker function."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run_shell(tmp_path, body, environment=None):
    bash = shutil.which("bash")
    if not bash or os.name == "nt":
        pytest.skip("Native POSIX Bash required")
    return subprocess.run(
        [
            bash,
            "-c",
            'set -eu; source "$1"; ' + body,
            "fixture",
            str(ROOT / "scripts/project-environment.sh"),
            str(ROOT),
        ],
        cwd=tmp_path,
        env={"PATH": os.environ["PATH"], **(environment or {})},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("name", ["CROW_TEST", "FAPAI_TEST"])
def test_host_process_bridge_exports_both_names_without_file_defaults(tmp_path, name):
    result = run_shell(
        tmp_path,
        'crow_sync_env; printf "%s|%s" "$CROW_TEST" "$FAPAI_TEST"',
        {name: "synthetic"},
    )
    assert result.returncode == 0 and result.stdout == "synthetic|synthetic"


def test_host_process_conflict_is_validated_before_any_pair_is_written(tmp_path):
    result = run_shell(
        tmp_path,
        'if crow_sync_env; then exit 33; fi; printf "%s" "${FAPAI_OTHER-unset}"',
        {
            "CROW_OTHER": "before",
            "CROW_TEST": "private-new",
            "FAPAI_TEST": "private-old",
        },
    )
    assert result.returncode == 0 and result.stdout == "unset"
    assert "CROW_TEST" in result.stderr and "private" not in result.stderr


def test_nas_source_boundary_keeps_file_priority_and_refuses_container_new_wire(
    tmp_path,
):
    source = (ROOT / "scripts/deploy-nas-central-api.sh").read_text()
    start = source.index('crow_source_env_file "$env_file"')
    block = source[start : source.index("postgres_container=", start)]
    path = tmp_path / "synthetic.env"
    path.write_text("FAPAI_NAS_DATA_ROOT=/synthetic/data\n")
    body = (
        'repo_root="$2"; env_file=synthetic.env; '
        + block
        + 'printf "%s|%s" "$CROW_NAS_DATA_ROOT" "$FAPAI_NAS_DATA_ROOT"'
    )
    result = run_shell(tmp_path, body, {"CROW_NAS_DATA_ROOT": "/synthetic/process"})
    assert result.returncode == 0 and result.stdout == "/synthetic/data|/synthetic/data"
    path.write_text(
        "UNRELATED_FIXTURE=private-value\nCROW_NAS_DATA_ROOT=/synthetic/data\n"
    )
    result = run_shell(
        tmp_path,
        'if crow_source_env_file synthetic.env "$2/tools/shell_environment_file.py" --legacy-container-env; then exit 33; fi; printf "%s" "${UNRELATED_FIXTURE-unset}"',
    )
    assert result.returncode == 0 and result.stdout == "unset"
    assert "CROW_NAS_DATA_ROOT -> FAPAI_NAS_DATA_ROOT" in result.stderr
    assert "private" not in result.stderr


def test_nas_rollback_keeps_runner_arguments_status_and_scoped_image_override(tmp_path):
    source = (ROOT / "scripts/deploy-nas-central-api.sh").read_text()
    block = source[
        source.index("rollback() {") : source.index("\n}", source.index("rollback() {"))
        + 2
    ]
    body = (
        r"""
crow_set_env CROW_IMAGE candidate
rollback_tag=synthetic-rollback
compose_project=fixture
env_file=synthetic.env
compose_file=compose.yml
docker() { printf '%s|%s|' "$CROW_IMAGE" "$FAPAI_IMAGE"; printf '%s,' "$@"; return 7; }
"""
        + block
        + r"""
status=0
rollback || status=$?
printf '\n%s|%s|%s' "$status" "$CROW_IMAGE" "$FAPAI_IMAGE"
"""
    )
    result = run_shell(tmp_path, body)
    assert result.returncode == 0, result.stderr
    assert (
        "synthetic-rollback|synthetic-rollback|compose,--project-name,fixture,--env-file,synthetic.env,-f,compose.yml,up,-d,--no-deps,--no-build,crow-api,"
        in result.stdout
    )
    assert result.stdout.endswith("7|candidate|candidate")
    assert 'command docker-compose "$@"' in source


def test_non_shell_unicode_line_separators_do_not_create_fake_declarations(tmp_path):
    for text in [
        "\u2028CROW_TEST=private-value\n",
        "CROW_TEST=private-value\u2028CROW_OTHER=value\n",
    ]:
        (tmp_path / "synthetic.env").write_text(text)
        result = run_shell(
            tmp_path,
            'crow_source_env_file synthetic.env "$2/tools/shell_environment_file.py"',
        )
        assert result.returncode != 0 and "private" not in result.stderr
