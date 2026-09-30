"""Saved desktop settings and scoped process overrides share one alias contract."""

import json
import os
from pathlib import Path

import pytest

from src.project_environment import EnvironmentAliasConflict
from tools.desktop_environment import environment_value
from tools.desktop_runtime_config import CONFIG_NAME, load_runtime_environment
from tools.pc1_desktop_recovery import RecoveryClient, RecoveryError


def write_config(root, values):
    path = root / CONFIG_NAME
    path.write_text(json.dumps({"version": 1, "environment": values}), encoding="utf-8")
    return path


@pytest.mark.parametrize("saved,process", [("FAPAI", "CROW"), ("CROW", "FAPAI")])
def test_process_alias_overrides_saved_group_without_rewriting_config(
    tmp_path, saved, process
):
    config = write_config(
        tmp_path,
        {
            saved + "_COOKIE_SNAPSHOT": "saved.json",
            saved + "_AUTH_LOCAL_CDP_PORT": "9227",
        },
    )
    before = config.read_bytes()
    supplied = {
        process + "_COOKIE_SNAPSHOT": "process.json",
        process + "_AUTH_LOCAL_CDP_PORT": "9333",
    }
    result = load_runtime_environment(tmp_path, supplied)
    assert result == supplied
    assert config.read_bytes() == before
    assert (
        environment_value("CROW_COOKIE_SNAPSHOT", environment=result, root=tmp_path)
        == "process.json"
    )


@pytest.mark.parametrize(
    "saved,process", [("FAPAI", "CROW"), ("CROW", "FAPAI"), ("FAPAI", "FAPAI")]
)
def test_empty_process_value_keeps_original_saved_value_fallback(
    tmp_path, saved, process
):
    write_config(
        tmp_path,
        {
            saved + "_COOKIE_SNAPSHOT": "saved.json",
            saved + "_AUTH_LOCAL_CDP_PORT": "9227",
        },
    )
    supplied = {process + "_COOKIE_SNAPSHOT": "", process + "_AUTH_LOCAL_CDP_PORT": ""}
    result = load_runtime_environment(tmp_path, supplied)
    for prefix in ("CROW", "FAPAI"):
        assert result[prefix + "_COOKIE_SNAPSHOT"] == str(tmp_path / "saved.json")
        assert result[prefix + "_AUTH_LOCAL_CDP_PORT"] == "9227"
    assert set(supplied.values()) == {""}


def test_saved_path_aliases_compare_lexically_without_filesystem_changes(tmp_path):
    write_config(
        tmp_path,
        {
            "CROW_AUTH_BROWSER_PROFILE_DIR": "profile/",
            "FAPAI_AUTH_BROWSER_PROFILE_DIR": str(tmp_path / "profile"),
        },
    )
    result = load_runtime_environment(tmp_path, {})
    assert environment_value(
        "CROW_AUTH_BROWSER_PROFILE_DIR", environment=result, root=tmp_path
    ) == str(tmp_path / "profile")
    assert not (tmp_path / "profile").exists()


def test_process_path_equivalence_keeps_relative_path_semantics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    values = {
        "CROW_COOKIE_SNAPSHOT": "cookies.json",
        "FAPAI_COOKIE_SNAPSHOT": str(tmp_path / "cookies.json"),
    }
    assert (
        environment_value(
            "CROW_COOKIE_SNAPSHOT",
            environment=values,
            root=tmp_path / "different-bundle",
        )
        == "cookies.json"
    )


@pytest.mark.parametrize("source", ["process", "saved"])
def test_desktop_conflicts_fail_closed_without_values(tmp_path, source):
    values = {
        "CROW_COOKIE_SNAPSHOT": "private-new.json",
        "FAPAI_COOKIE_SNAPSHOT": "private-old.json",
    }
    write_config(
        tmp_path,
        values if source == "saved" else {"CROW_COOKIE_SNAPSHOT": "saved.json"},
    )
    with pytest.raises(RecoveryError, match="^runtime_config_invalid$") as error:
        load_runtime_environment(tmp_path, values if source == "process" else {})
    assert "private-" not in str(error.value.__cause__)


def test_injected_recovery_client_does_not_read_global_credentials(
    tmp_path, monkeypatch
):
    token = tmp_path / "token"
    token.write_text("synthetic-desktop-token-123456", encoding="utf-8")
    monkeypatch.setenv("CROW_NAS_AUTH_RECOVERY_TOKEN_FILE", "global-private-new")
    monkeypatch.setenv("FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE", "global-private-old")
    values = {
        "CROW_COLLECTOR_API_BASE": "http://127.0.0.1:18001",
        "CROW_NAS_AUTH_RECOVERY_TOKEN_FILE": str(token),
        "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE": str(token.parent / "." / token.name),
    }
    client = RecoveryClient("http://127.0.0.1:18001", tmp_path, environment=values)
    assert client.headers["X-Fapai-Recovery-Token"] == "synthetic-desktop-token-123456"
    with pytest.raises(RecoveryError, match="api_not_configured"):
        RecoveryClient("http://127.0.0.1:18002", tmp_path, environment=values)


def test_link_and_target_aliases_are_not_silently_conflated(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(EnvironmentAliasConflict):
        environment_value(
            "CROW_AUTH_BROWSER_PROFILE_DIR",
            environment={
                "CROW_AUTH_BROWSER_PROFILE_DIR": str(link),
                "FAPAI_AUTH_BROWSER_PROFILE_DIR": str(target),
            },
            root=tmp_path,
        )
    assert link.is_symlink() and target.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="Windows path case and UNC semantics")
def test_windows_path_aliases_accept_case_and_unc_equivalence():
    values = {
        "CROW_COOKIE_SNAPSHOT": r"\\server\Share\cookies.json",
        "FAPAI_COOKIE_SNAPSHOT": r"\\SERVER\share\cookies.json",
    }
    assert (
        environment_value(
            "CROW_COOKIE_SNAPSHOT", environment=values, root=Path("C:/bundle")
        )
        == values["CROW_COOKIE_SNAPSHOT"]
    )


def test_browser_configuration_conflict_precedes_browser_io(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from tools import pc1_desktop_auth

    listing = Mock()
    launch = Mock()
    monkeypatch.setattr(
        pc1_desktop_auth.handoff.taobao_login_health, "list_cdp_targets", listing
    )
    monkeypatch.setattr(pc1_desktop_auth.subprocess, "run", launch)
    with pytest.raises(EnvironmentAliasConflict):
        pc1_desktop_auth.open_challenge(
            "https://sf-item.taobao.com/sf_item/123.htm",
            "http://127.0.0.1:9225",
            9225,
            tmp_path,
            environment={
                "CROW_AUTH_BROWSER_PATH": "new",
                "FAPAI_AUTH_BROWSER_PATH": "old",
            },
        )
    listing.assert_not_called()
    launch.assert_not_called()


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI"])
def test_settings_configuration_uses_scoped_aliases(tmp_path, monkeypatch, prefix):
    from tools import desktop_settings_client

    ca = tmp_path / "ca.pem"
    token = tmp_path / "operator.token"
    ca.write_text("synthetic certificate fixture", encoding="utf-8")
    token.write_text("synthetic token fixture", encoding="utf-8")
    env = {
        prefix + "_SETTINGS_API_BASE": "https://example.invalid",
        prefix + "_SETTINGS_CA_FILE": str(ca),
        prefix + "_ENGINE_OPERATOR_TOKEN_FILE": str(token),
    }
    monkeypatch.setattr(
        desktop_settings_client, "load_runtime_environment", lambda _: env
    )
    assert desktop_settings_client.execute({"action": "config"}, tmp_path) == {
        "ok": True,
        "origin": "https://example.invalid",
        "configured": True,
    }
