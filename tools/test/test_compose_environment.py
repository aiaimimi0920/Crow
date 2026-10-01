"""Read-only alias preparation and Docker entrypoint mapping regression tests."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.compose_environment import prepare_environment
from src.project_environment import EnvironmentAliasConflict
from tools import crow_compose, docker_entrypoint


@pytest.mark.parametrize("source", ["CROW", "FAPAI", "BOTH"])
def test_scoped_source_aliases_do_not_create_or_move_data(
    tmp_path, monkeypatch, source
):
    monkeypatch.setenv("CROW_DATA_ROOT_HOST", "unrelated-global")
    values = {
        prefix + "_DATA_ROOT_HOST": str(tmp_path / "existing")
        for prefix in (["CROW", "FAPAI"] if source == "BOTH" else [source])
    }
    before = dict(values)
    result = prepare_environment(tmp_path, file_values=values, process={})
    assert (
        result["CROW_DATA_ROOT_HOST"]
        == result["FAPAI_DATA_ROOT_HOST"]
        == str(tmp_path / "existing")
    )
    assert values == before and not list(tmp_path.iterdir())


def test_explicit_process_and_file_precedence_are_alias_groups(tmp_path):
    files = {
        "CROW_DATA_ROOT_HOST": "file-new",
        "FAPAI_DATA_ROOT_HOST": "file-old",
        "OPENAI_MODEL": "file",
    }
    process = {"FAPAI_DATA_ROOT_HOST": "process", "OPENAI_MODEL": "process"}
    result = prepare_environment(tmp_path, file_values=files, process=process)
    assert result["CROW_DATA_ROOT_HOST"] == result["FAPAI_DATA_ROOT_HOST"] == "process"
    assert result["OPENAI_MODEL"] == "process"
    process["CROW_DATA_ROOT_HOST"] = "conflicting-process"
    result = prepare_environment(
        tmp_path,
        file_values=files,
        process=process,
        explicit={"CROW_DATA_ROOT_HOST": "explicit"},
    )
    assert result["CROW_DATA_ROOT_HOST"] == result["FAPAI_DATA_ROOT_HOST"] == "explicit"


def test_path_equivalence_blank_roots_and_nonpath_empty_values(tmp_path):
    result = prepare_environment(
        tmp_path,
        file_values={"FAPAI_DATA_ROOT_HOST": "data", "FAPAI_NODE_ID": "saved"},
        process={"CROW_DATA_ROOT_HOST": "", "CROW_NODE_ID": ""},
    )
    assert result["CROW_DATA_ROOT_HOST"] == "data"
    assert result["CROW_NODE_ID"] == result["FAPAI_NODE_ID"] == ""
    result = prepare_environment(
        tmp_path,
        file_values={},
        process={
            "CROW_DATA_ROOT_HOST": str(tmp_path / "data") + "/",
            "FAPAI_DATA_ROOT_HOST": "data",
        },
    )
    assert result["CROW_DATA_ROOT_HOST"] == result["FAPAI_DATA_ROOT_HOST"]


def test_conflict_rejected_without_values_or_filesystem_changes(tmp_path):
    with pytest.raises(EnvironmentAliasConflict) as error:
        prepare_environment(
            tmp_path,
            file_values={},
            process={
                "CROW_DATA_ROOT_HOST": "private-new",
                "FAPAI_DATA_ROOT_HOST": "private-old",
            },
        )
    assert "private-" not in str(error.value)
    assert not list(tmp_path.iterdir())


def test_compose_uses_inert_json_model_and_never_echoes_backend_secrets(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        model = json.loads(kwargs["input"])
        assert model["services"]["env-inspection"]["image"] == "scratch"
        assert "volumes" not in model["services"]["env-inspection"]
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "services": {
                        "env-inspection": {
                            "environment": {"CROW_LITERAL": "value$$literal"}
                        }
                    }
                }
            ),
            "",
        )

    assert crow_compose.inspect_file_environment(tmp_path, [], {}, runner=runner) == {
        "CROW_LITERAL": "value$literal"
    }
    assert calls[0][0][-4:] == ["config", "--format", "json", "--no-path-resolution"]
    with pytest.raises(crow_compose.ComposeEnvironmentError) as error:
        crow_compose.inspect_file_environment(
            tmp_path,
            [],
            {},
            runner=lambda *_a, **_kw: SimpleNamespace(
                returncode=1, stderr="private-secret", stdout=""
            ),
        )
    assert "private-secret" not in str(error.value)


def test_missing_alias_interpolation_reaches_fixed_point_without_freezing_file_values(
    tmp_path,
):
    calls = []

    def reader(root, files, process, *, interpolation=None):
        calls.append(dict(process))
        return {
            "CROW_NODE_ID": "fixture",
            "CROW_COOKIE_SNAPSHOT": "/nodes/"
            + (interpolation or {}).get("FAPAI_NODE_ID", "")
            + "/cookies.json",
        }

    result = crow_compose.resolve_environment(tmp_path, [], {}, {}, reader=reader)
    assert result["FAPAI_COOKIE_SNAPSHOT"] == "/nodes/fixture/cookies.json"
    assert all(call == {} for call in calls)


@pytest.mark.parametrize(
    "mode", ["seed-collector", "detail-worker", "detail-analysis-worker", "api"]
)
def test_docker_entrypoint_accepts_canonical_and_legacy_mappings_without_global_reads(
    monkeypatch, mode
):
    monkeypatch.setenv("CROW_RUN_MODE", "unrelated")
    old = {
        "FAPAI_RUN_MODE": mode,
        "FAPAI_NODE_ID": "fixture",
        "FAPAI_OUTPUT_DIR": "/data/output",
        "FAPAI_DETAIL_TARGET_SUCCESS": "7",
    }
    new = {"CROW_" + key[6:]: value for key, value in old.items()}
    assert (
        docker_entrypoint.build_command(old)
        == docker_entrypoint.build_command(new)
        == docker_entrypoint.build_command({**old, **new})
    )


def test_explicit_compose_project_directory_wins_over_first_file(tmp_path):
    inputs = crow_compose.compose_inputs(
        [
            "-p",
            "fixture",
            "--project-directory",
            str(tmp_path),
            "-f",
            "nested/compose.yml",
            "--env-file",
            "fixture.env",
            "config",
        ],
        tmp_path,
    )
    assert inputs.root == tmp_path and inputs.env_files == (tmp_path / "fixture.env",)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows drive and UNC semantics")
def test_windows_compose_root_equivalence_and_drive_relative_rejection():
    root = Path("C:/bundle")
    for first, second in [("C:/", "C:\\"), ("//server/share/", "//SERVER/SHARE")]:
        result = prepare_environment(
            root,
            file_values={},
            process={"CROW_DATA_ROOT_HOST": first, "FAPAI_DATA_ROOT_HOST": second},
        )
        assert result["CROW_DATA_ROOT_HOST"] == result["FAPAI_DATA_ROOT_HOST"] == first
    with pytest.raises(EnvironmentAliasConflict):
        prepare_environment(
            root,
            file_values={},
            process={"CROW_DATA_ROOT_HOST": "C:/", "FAPAI_DATA_ROOT_HOST": "C:"},
        )
