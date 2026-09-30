"""The same API/runtime configuration works under new and legacy spellings."""

from __future__ import annotations

import json

import pytest

from src import collection_api_credentials as credentials
from src import collection_engine_restart as restart
from src.project_data_paths import resolve_collection_data_dir
from src.project_environment import EnvironmentAliasConflict
from src.server_request_guard import _env_flag
from src.storage.repository import database_settings_from_env
from src.storage.repository_context import _shared_data_root_candidates
from tools import run_isolated_collection_api


def configure(monkeypatch, prefix, key, value):
    for name in ("CROW_" + key, "FAPAI_" + key):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(prefix + "_" + key, value)


@pytest.mark.parametrize("prefix", ["FAPAI", "CROW"])
def test_database_url_and_flag_semantics_are_compatible(monkeypatch, prefix):
    configure(monkeypatch, prefix, "DB_URL", "sqlite:///:memory:")
    configure(monkeypatch, prefix, "DB_ENABLED", "true")
    configure(monkeypatch, prefix, "DB_ECHO", "0")
    configure(monkeypatch, prefix, "DB_ENABLE_POSTGIS", "off")
    configure(monkeypatch, prefix, "DB_AUTO_CREATE", "false")
    settings = database_settings_from_env()
    assert settings.url == "sqlite:///:memory:"
    assert settings.enabled is True
    assert settings.echo is False
    assert settings.enable_postgis is False
    assert settings.auto_create is False


@pytest.mark.parametrize("prefix", ["FAPAI", "CROW"])
def test_collection_subdirectory_and_cli_use_the_same_env(
    tmp_path, monkeypatch, capsys, prefix
):
    target = tmp_path / "collection-data"
    configure(monkeypatch, prefix, "DATA_ROOT", str(target))
    assert resolve_collection_data_dir(tmp_path) == target
    assert run_isolated_collection_api.main(["--print-config"]) == 0
    assert json.loads(capsys.readouterr().out)["data_dir"] == str(target)
    assert not target.exists()


@pytest.mark.parametrize("prefix", ["FAPAI", "CROW"])
def test_worker_credentials_remain_bound_to_the_configured_api(
    tmp_path, monkeypatch, prefix
):
    token = tmp_path / "worker.token"
    token.write_text("w" * 48, encoding="utf-8")
    configure(monkeypatch, prefix, "COLLECTION_WORKER_TOKEN_FILE", str(token))
    configure(monkeypatch, prefix, "API_BASE_URL", "http://127.0.0.1:8011/api")
    configure(monkeypatch, prefix, "NAS_AUTH_RECOVERY_TOKEN_FILE", "")
    assert credentials.worker_token() == "w" * 48
    assert (
        credentials.request_headers("http://127.0.0.1:8011/api/collection/seed/next")[
            credentials.WORKER_TOKEN_HEADER
        ]
        == "w" * 48
    )
    assert (
        credentials.request_headers("http://127.0.0.1:8999/api/collection/seed/next")
        == {}
    )
    token.write_text("r" * 48, encoding="utf-8")
    assert credentials.worker_token() == "r" * 48


@pytest.mark.parametrize("prefix", ["FAPAI", "CROW"])
def test_restart_tokens_and_boolean_flags_support_either_spelling(
    tmp_path, monkeypatch, prefix
):
    token = tmp_path / "operator.token"
    token.write_text("o" * 48, encoding="utf-8")
    configure(monkeypatch, prefix, "ENGINE_OPERATOR_TOKEN_FILE", str(token))
    assert restart.token("operator") == "o" * 48
    configure(monkeypatch, prefix, "TEST_FLAG", "0")
    assert _env_flag("CROW_TEST_FLAG", "1") is False
    configure(monkeypatch, prefix, "TEST_FLAG", "")
    assert (
        _env_flag("CROW_TEST_FLAG", "1") is True
    )  # Existing caller's or-default rule.


def test_management_root_aliases_keep_path_equivalence(monkeypatch, tmp_path):
    root = tmp_path / "management"
    monkeypatch.setenv("CROW_DATA_ROOT_HOST", str(root) + "/")
    monkeypatch.setenv("FAPAI_DATA_ROOT_HOST", str(root))
    assert root in _shared_data_root_candidates()
    assert not root.exists()


def test_runtime_conflict_is_closed_without_credential_values(monkeypatch):
    monkeypatch.setenv("CROW_COLLECTION_WORKER_TOKEN_FILE", "new-private-path")
    monkeypatch.setenv("FAPAI_COLLECTION_WORKER_TOKEN_FILE", "old-private-path")
    with pytest.raises(EnvironmentAliasConflict) as error:
        credentials.worker_token()
    assert "private-path" not in str(error.value)
