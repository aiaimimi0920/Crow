"""Compose selectors are parsed once, or rejected before any Docker invocation."""

import pytest

from tools.compose_arguments import (
    ComposeEnvironmentError,
    compose_inputs,
    reject_indirect_selectors,
)


@pytest.mark.parametrize(
    "options",
    [
        ["-f", "nested/first.yml", "-f", "other/second.yml"],
        ["-fnested/first.yml", "--file=other/second.yml"],
        ["-f=nested/first.yml", "--file=other/second.yml"],
        ["--file", "nested/first.yml", "--file", "other/second.yml"],
    ],
)
def test_first_of_multiple_files_selects_project_root(tmp_path, options):
    inputs = compose_inputs(
        [*options, "--env-file", "settings.env", "config"], tmp_path
    )
    assert inputs.root == tmp_path / "nested"
    assert inputs.env_files == (tmp_path / "settings.env",)
    assert inputs.explicit_files and inputs.explicit_env_files


@pytest.mark.parametrize("position", ["before", "after"])
def test_explicit_project_directory_wins_for_multifile_combinations(tmp_path, position):
    project = ["--project-directory", str(tmp_path)]
    files = ["-fnested/first.yml", "-f", "other/second.yml"]
    args = project + files if position == "before" else files + project
    inputs = compose_inputs(
        ["-pfixture", "--profile=analysis", *args, "config", "--format", "json"],
        tmp_path,
    )
    assert inputs.root == tmp_path and inputs.explicit_files


@pytest.mark.parametrize(
    "arguments",
    [
        ["-f"],
        ["-f", "--env-file", "other"],
        ["--env-file="],
        ["--project-directory", "a", "--project-directory=b", "config"],
        ["--unknown", "private-path", "-f", "other.yml", "config"],
        ["--project-name"],
        ["-f-", "config"],
        ["config", "-fother.yml"],
        ["up", "--env-file", "other.env"],
        ["--file=https://private.invalid/file.yml", "config"],
    ],
)
def test_ambiguous_or_unsupported_selectors_fail_closed(tmp_path, arguments):
    with pytest.raises(ComposeEnvironmentError) as error:
        compose_inputs(arguments, tmp_path)
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "key, option",
    [
        ("COMPOSE_FILE", ["-f", "compose.yml"]),
        ("COMPOSE_ENV_FILES", ["--env-file", "settings.env"]),
    ],
)
def test_indirect_selector_is_checked_for_both_process_and_resolved_file_sources(
    tmp_path, key, option
):
    implicit = compose_inputs(["config"], tmp_path)
    with pytest.raises(ComposeEnvironmentError):
        reject_indirect_selectors(implicit, {key: "private-input"})
    explicit = compose_inputs([*option, "config"], tmp_path)
    reject_indirect_selectors(explicit, {key: "private-input"})


def test_multiple_env_files_preserve_order_and_are_relative_to_calling_directory(
    tmp_path,
):
    inputs = compose_inputs(
        [
            "--project-directory=subdir",
            "--env-file=first.env",
            "--env-file",
            "second.env",
            "config",
        ],
        tmp_path,
    )
    assert inputs.env_files == (tmp_path / "first.env", tmp_path / "second.env")
