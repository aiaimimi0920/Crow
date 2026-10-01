"""Actual Docker Compose config only: no images, containers, volumes or host data."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.project_environment import EnvironmentAliasConflict
from tools.crow_compose import resolve_environment

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def compose_process():
    process = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CROW_", "FAPAI_", "OPENAI_"))
    }
    try:
        check = subprocess.run(
            ["docker", "compose", "version"],
            env=process,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        available = check.returncode == 0
    except (OSError, subprocess.SubprocessError):
        available = False
    if not available:
        if os.environ.get("CROW_TEST_COMPOSE") == "1":
            pytest.fail("Required Docker Compose config validation is unavailable")
        pytest.skip("Docker Compose unavailable; required on Linux CI")
    return process


def test_real_templates_keep_legacy_mounts_images_and_services(
    tmp_path, compose_process
):
    for name in (
        "docker-compose.collection.yml",
        "docker-compose.collection.host-bind.yml",
    ):
        shutil.copyfile(ROOT / name, tmp_path / name)
    data = tmp_path / "legacy-existing-data"
    data.mkdir()
    sentinel = data / "existing-record"
    sentinel.write_bytes(b"preserve this record")
    models = []
    for prefix in ("FAPAI", "CROW", "BOTH"):
        config = tmp_path / "synthetic.env"
        config.write_text(
            "\n".join(
                f"{name}_DATA_ROOT_HOST='{data.as_posix()}'"
                for name in (["FAPAI", "CROW"] if prefix == "BOTH" else [prefix])
            )
            + "\n",
            encoding="utf-8",
        )
        prepared = resolve_environment(tmp_path, [config], compose_process, {})
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                "crow-compatibility-fixture",
                "--env-file",
                str(config),
                "-f",
                "docker-compose.collection.yml",
                "-f",
                "docker-compose.collection.host-bind.yml",
                "config",
                "--format",
                "json",
            ],
            cwd=tmp_path,
            env=prepared,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, "Synthetic Compose config did not validate"
        models.append(json.loads(result.stdout))
        assert sentinel.read_bytes() == b"preserve this record"
        assert list(data.iterdir()) == [sentinel]
    assert models[0] == models[1] == models[2]
    worker = models[0]["services"]["fapaifang-seed-collector"]
    assert worker["image"] == "fapaifang-collector:local"
    assert {Path(row["source"]) for row in worker["volumes"]} == {
        data / name for name in ("output", "datas", "jobs", "secrets")
    }


def test_compose_parser_handles_quotes_dollars_and_cross_alias_references(
    tmp_path, compose_process
):
    config = tmp_path / "synthetic.env"
    config.write_text(
        "CROW_NODE_ID=fixture\nCROW_LITERAL='dollar$value # literal'\nCROW_COOKIE_SNAPSHOT=\"/nodes/${FAPAI_NODE_ID}/cookies.json\"\n",
        encoding="utf-8",
    )
    before = config.read_bytes()
    result = resolve_environment(tmp_path, [config], compose_process, {})
    assert result["CROW_LITERAL"] == result["FAPAI_LITERAL"] == "dollar$value # literal"
    assert (
        result["CROW_COOKIE_SNAPSHOT"]
        == result["FAPAI_COOKIE_SNAPSHOT"]
        == "/nodes/fixture/cookies.json"
    )
    assert config.read_bytes() == before


def test_file_conflicts_fail_before_any_operational_compose_command(
    tmp_path, compose_process
):
    config = tmp_path / "synthetic.env"
    config.write_text(
        "CROW_DATA_ROOT_HOST=private-new\nFAPAI_DATA_ROOT_HOST=private-old\n",
        encoding="utf-8",
    )
    with pytest.raises(EnvironmentAliasConflict) as error:
        resolve_environment(tmp_path, [config], compose_process, {})
    assert "private-" not in str(error.value)
    result = resolve_environment(
        tmp_path,
        [config],
        {**compose_process, "FAPAI_DATA_ROOT_HOST": "chosen-process"},
        {},
    )
    assert (
        result["CROW_DATA_ROOT_HOST"]
        == result["FAPAI_DATA_ROOT_HOST"]
        == "chosen-process"
    )
    assert {path.name for path in tmp_path.iterdir()} == {"synthetic.env"}


def test_compact_multifile_and_project_directory_match_actual_compose(
    tmp_path, compose_process
):
    from tools.compose_arguments import compose_inputs

    source = tmp_path / "source"
    source.mkdir()
    selected = tmp_path / "selected"
    selected.mkdir()
    first = source / "first.json"
    second = source / "second.json"
    first.write_text(
        json.dumps(
            {
                "services": {
                    "fixture": {
                        "image": "scratch",
                        "volumes": [
                            {
                                "type": "bind",
                                "source": "${FAPAI_DATA_ROOT_HOST}/output",
                                "target": "/data",
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps({"services": {"fixture": {"environment": {"MARKER": "stable"}}}}),
        encoding="utf-8",
    )
    config = tmp_path / "synthetic.env"
    config.write_text(
        f"CROW_DATA_ROOT_HOST=relative-data\nFAPAI_DATA_ROOT_HOST={selected.as_posix()}/relative-data/\n",
        encoding="utf-8",
    )
    arguments = [
        f"-f{first}",
        f"--file={second}",
        f"--project-directory={selected}",
        "--env-file",
        str(config),
        "config",
        "--format",
        "json",
    ]
    inputs = compose_inputs(arguments, tmp_path)
    assert inputs.root == selected
    prepared = resolve_environment(inputs.root, inputs.env_files, compose_process, {})
    result = subprocess.run(
        ["docker", "compose", *arguments],
        cwd=tmp_path,
        env=prepared,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "Synthetic selector configuration did not validate"
    model = json.loads(result.stdout)
    assert model["services"]["fixture"]["volumes"][0]["source"] == str(
        selected / "relative-data/output"
    )
    assert not (selected / "relative-data").exists()


@pytest.mark.parametrize("key", ["COMPOSE_FILE", "COMPOSE_ENV_FILES"])
def test_indirect_selector_from_env_file_is_rejected_by_cli(
    tmp_path, compose_process, monkeypatch, capsys, key
):
    from tools import crow_compose

    for name in list(os.environ):
        if name.startswith(("CROW_", "FAPAI_", "COMPOSE_")):
            monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(key + "=private-indirect-input\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert crow_compose.main(["--check", "--", "config"]) == 2
    captured = capsys.readouterr()
    assert "explicitly" in captured.err and "private-indirect-input" not in captured.err
    assert captured.out == ""


def test_container_wire_conflict_stops_before_any_operational_command(
    tmp_path, compose_process, monkeypatch, capsys
):
    from tools import crow_compose

    for key in list(os.environ):
        if key.startswith(("CROW_", "FAPAI_", "COMPOSE_")):
            monkeypatch.delenv(key, raising=False)
    config = tmp_path / "synthetic.env"
    config.write_text("CROW_TEST_FLAG=private-file-value\n", encoding="utf-8")
    model = tmp_path / "compose.json"
    model.write_text(
        json.dumps(
            {
                "services": {
                    "fixture": {
                        "image": "scratch",
                        "env_file": [str(config)],
                        "environment": {"FAPAI_TEST_FLAG": "private-fixed-value"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    calls = []
    real_run = subprocess.run
    real_validate = crow_compose.validate_service_environment

    def config_only(command, **options):
        calls.append(command)
        assert command[:2] == ["docker", "compose"] and "config" in command
        assert "up" not in command, "Operational command must never be reached"
        return real_run(command, **options)

    monkeypatch.setattr(crow_compose.subprocess, "run", config_only)
    monkeypatch.setattr(
        crow_compose,
        "validate_service_environment",
        lambda arguments, environment: real_validate(
            arguments, environment, runner=config_only
        ),
    )
    arguments = ["--", "--env-file", str(config), "-f", str(model), "up", "--detach"]
    assert crow_compose.main(arguments) == 2
    captured = capsys.readouterr()
    assert "CROW_TEST_FLAG" in captured.err and "FAPAI_TEST_FLAG" in captured.err
    assert "legacy wire" in captured.err and "private-" not in captured.err
    assert len(calls) == 1 and calls[0][-3:] == ["config", "--format", "json"]
    config.write_text("FAPAI_TEST_FLAG=private-file-value\n", encoding="utf-8")
    assert crow_compose.main(["--check", *arguments]) == 0
    assert all("up" not in command for command in calls)
