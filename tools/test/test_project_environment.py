"""Compatibility primitives only: no global environment replacement or I/O."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from src.project_environment import (
    EnvironmentAliasConflict,
    getenv,
    require_env,
    set_env,
    setdefault_env,
)


@pytest.mark.parametrize("requested", ["CROW_SAMPLE", "FAPAI_SAMPLE"])
@pytest.mark.parametrize("configured", ["CROW_SAMPLE", "FAPAI_SAMPLE"])
@pytest.mark.parametrize("value", ["value", "", "0", "false", " 空格 "])
def test_both_spellings_preserve_values_without_mutation(requested, configured, value):
    environment = {configured: value}
    before = dict(environment)
    assert getenv(requested, "fallback", reader=environment.get) == value
    assert environment == before


def test_absent_values_keep_default_type_and_required_behavior():
    assert getenv("CROW_MISSING", reader={}.get) is None
    assert getenv("CROW_MISSING", False, reader={}.get) is False
    assert getenv("CROW_MISSING", 7, reader={}.get) == 7
    with pytest.raises(KeyError, match="CROW_MISSING"):
        require_env("FAPAI_MISSING", reader={}.get)
    assert require_env("CROW_EMPTY", reader={"FAPAI_EMPTY": ""}.get) == ""


def test_equal_aliases_are_accepted_but_conflicts_never_reveal_values():
    assert (
        getenv("CROW_TOKEN", reader={"CROW_TOKEN": "same", "FAPAI_TOKEN": "same"}.get)
        == "same"
    )
    environment = {
        "CROW_TOKEN": "private-new-value",
        "FAPAI_TOKEN": "private-old-value",
    }
    with pytest.raises(EnvironmentAliasConflict) as error:
        getenv("CROW_TOKEN", reader=environment.get)
    assert (
        str(error.value) == "Conflicting environment aliases: CROW_TOKEN, FAPAI_TOKEN"
    )
    assert "private" not in str(error.value)
    assert environment == {
        "CROW_TOKEN": "private-new-value",
        "FAPAI_TOKEN": "private-old-value",
    }


def test_empty_and_nonempty_explicit_aliases_conflict():
    with pytest.raises(EnvironmentAliasConflict):
        getenv("CROW_SAMPLE", reader={"CROW_SAMPLE": "", "FAPAI_SAMPLE": "legacy"}.get)


def test_reader_is_dynamic_and_never_falls_back_to_process(monkeypatch):
    monkeypatch.delenv("FAPAI_SAMPLE", raising=False)
    monkeypatch.setenv("CROW_SAMPLE", "process-value")
    environment = {"FAPAI_SAMPLE": "first"}
    assert getenv("CROW_SAMPLE", reader=environment.get) == "first"
    environment["FAPAI_SAMPLE"] = "second"
    assert getenv("CROW_SAMPLE", reader=environment.get) == "second"
    assert (
        getenv("CROW_SAMPLE", "isolated-default", reader={}.get) == "isolated-default"
    )
    assert getenv("CROW_SAMPLE") == "process-value"


def test_non_project_names_have_no_alias_or_value_conversion():
    environment = {"PATH": "native-path", "FAPAI_PATH": "unrelated"}
    assert getenv("PATH", reader=environment.get) == "native-path"
    set_env("PATH", "updated", environ=environment)
    assert environment == {"PATH": "updated", "FAPAI_PATH": "unrelated"}


def test_explicit_writes_update_both_names_without_touching_other_settings():
    environment = {
        "CROW_KEY": "new-before",
        "FAPAI_KEY": "old-before",
        "OTHER": "untouched",
    }
    set_env("CROW_KEY", "explicit", environ=environment)
    assert environment == {
        "CROW_KEY": "explicit",
        "FAPAI_KEY": "explicit",
        "OTHER": "untouched",
    }
    set_env("FAPAI_KEY", "legacy-writer", environ=environment)
    assert getenv("CROW_KEY", reader=environment.get) == "legacy-writer"
    with pytest.raises(TypeError, match="must be strings"):
        set_env("CROW_KEY", None, environ=environment)


def test_setdefault_keeps_existing_empty_values_and_is_read_only_when_present():
    environment = {"FAPAI_KEY": ""}
    assert setdefault_env("CROW_KEY", "default", environ=environment) == ""
    assert environment == {"FAPAI_KEY": ""}
    assert setdefault_env("CROW_NEW", "default", environ=environment) == "default"
    assert environment["CROW_NEW"] == environment["FAPAI_NEW"] == "default"
    environment["FAPAI_NEW"] = "conflict"
    before = dict(environment)
    with pytest.raises(EnvironmentAliasConflict):
        setdefault_env("CROW_NEW", "unused", environ=environment)
    assert environment == before


def test_helpers_do_not_expose_half_written_alias_pairs():
    environment = {}
    set_env("CROW_KEY", "0", environ=environment)

    def write_values():
        for index in range(1000):
            set_env("CROW_KEY", str(index), environ=environment)

    def read_values():
        for _ in range(1000):
            assert getenv("CROW_KEY", reader=environment.get).isdigit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        writes = executor.submit(write_values)
        reads = executor.submit(read_values)
        writes.result()
        reads.result()
