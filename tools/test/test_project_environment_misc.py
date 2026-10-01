"""Remaining configuration aliases using pure readers and fake controllers."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from src import llm_openai_compatible, llm_qualification_pool
from src.collection.adapters import auction_communities
from src.llm_qualification_store import QualificationStore
from src.project_environment import EnvironmentAliasConflict
from tools import (
    avm_data_loader,
    cdp_browser_identity,
    taobao_login_health,
    taobao_sf_locations,
)


def configure(monkeypatch, prefix, **settings):
    for key, value in settings.items():
        for spelling in ("CROW", "FAPAI"):
            monkeypatch.delenv(spelling + "_" + key, raising=False)
            if prefix in (spelling, "BOTH"):
                monkeypatch.setenv(spelling + "_" + key, value)


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
def test_analysis_and_community_config_preserve_existing_storage(
    monkeypatch, tmp_path, prefix
):
    index = tmp_path / "community.json"
    index.write_text("[]", encoding="utf-8")
    configure(
        monkeypatch,
        prefix,
        ANALYSIS_MODEL_POOL_ENABLED="1",
        ANALYSIS_MODEL_POOL_PATH=str(tmp_path / "pool.sqlite3"),
        COMMUNITY_INDEX_PATH=str(index),
        DB_PREFER_ANALYTICS_SOURCE="0",
    )
    assert llm_qualification_pool.pool_enabled() is True
    assert QualificationStore.resolve_path() == tmp_path / "pool.sqlite3"
    assert auction_communities._default_index_path() == index
    assert avm_data_loader._env_flag("CROW_DB_PREFER_ANALYTICS_SOURCE", True) is False
    assert list(tmp_path.iterdir()) == [index]
    assert index.read_text() == "[]"


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
def test_llm_proxy_aliases_keep_explicit_openai_precedence(monkeypatch, prefix):
    for key in ("OPENAI_PROXY", "OPENAI_HTTP_PROXY", "OPENAI_HTTPS_PROXY"):
        monkeypatch.delenv(key, raising=False)
    configure(
        monkeypatch,
        prefix,
        LLM_PROXY="http://proxy.invalid:8888",
        LLM_HTTP_PROXY="",
        LLM_HTTPS_PROXY="",
        HTTP_PROXY="",
        HTTPS_PROXY="",
    )
    assert llm_openai_compatible._get_openai_compatible_proxies(
        "https://model.invalid"
    ) == {"http": "http://proxy.invalid:8888", "https": "http://proxy.invalid:8888"}
    monkeypatch.setenv("OPENAI_HTTP_PROXY", "http://explicit.invalid:8888")
    assert (
        llm_openai_compatible._get_openai_compatible_proxies("https://model.invalid")[
            "http"
        ]
        == "http://explicit.invalid:8888"
    )


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
def test_health_and_location_facades_read_aliases_without_requests(monkeypatch, prefix):
    configure(
        monkeypatch,
        prefix,
        REPORT_CDP_ENDPOINT="http://report.invalid:9223",
        CDP_ENDPOINT_HOST="http://location.invalid:9223",
    )
    assert (
        taobao_login_health.resolve_captcha_report_cdp_endpoint("unused")
        == "http://report.invalid:9223"
    )
    args = taobao_sf_locations.build_parser().parse_args(["crawl"])
    assert args.cdp_endpoint == "http://location.invalid:9223"


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
def test_identity_controller_config_uses_aliases_with_fake_io(
    monkeypatch, tmp_path, prefix
):
    configure(
        monkeypatch,
        prefix,
        BROWSER_USER_AGENT="fixture agent",
        BROWSER_IDENTITY_FULL_VERSION="151.0.0.0",
        BROWSER_IDENTITY_READY_PATH=str(tmp_path / "ready"),
    )
    factory = Mock()
    monkeypatch.setattr(cdp_browser_identity, "BrowserIdentityController", factory)
    monkeypatch.setattr(cdp_browser_identity.signal, "signal", Mock())
    monkeypatch.setattr(sys, "argv", ["identity"])
    assert cdp_browser_identity.main() == 0
    assert factory.call_args.kwargs["user_agent"] == "fixture agent"
    assert factory.call_args.kwargs["ready_path"] == tmp_path / "ready"
    factory.return_value.run.assert_called_once_with()
    assert not list(tmp_path.iterdir())


def test_proxy_conflict_does_not_fall_back_to_generic_proxy(monkeypatch):
    monkeypatch.delenv("OPENAI_PROXY", raising=False)
    monkeypatch.setenv("CROW_LLM_PROXY", "private-new")
    monkeypatch.setenv("FAPAI_LLM_PROXY", "private-old")
    with pytest.raises(EnvironmentAliasConflict) as error:
        llm_openai_compatible._get_openai_compatible_proxies("https://model.invalid")
    assert "private-" not in str(error.value)


def test_browser_identity_help_has_complete_standalone_imports(tmp_path):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    script = Path(__file__).resolve().parents[1] / "cdp_browser_identity.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--ready-path" in result.stdout
    assert not list(tmp_path.iterdir())
