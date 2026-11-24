"""GPT is an explicit permission, not a bypass of model qualification."""

import pytest

from src.collection_engine_restart import RestartError
from src.collection_settings_schema import validate
from src.llm_analysis_policy import gpt_models_enabled, require_non_gpt_analysis_model
from src.llm_model_selector import LLMBackendUnavailableError
from src.llm_qualification_pool import QualifiedModelPool, eligible_model
from tools.pc2_settings_model import inventory, render
from tools.test.collection_settings_fixtures import config_fixture, model_fixture
from tools.test.test_llm_qualification_pool import make_pool


@pytest.mark.parametrize("name", ["gpt-6.1-sol", "gpt-6-luna"])
def test_permission_defaults_off_and_supports_explicit_optin(monkeypatch, name):
    monkeypatch.delenv("CROW_ANALYSIS_ALLOW_GPT", raising=False)
    monkeypatch.delenv("FAPAI_ANALYSIS_ALLOW_GPT", raising=False)
    with pytest.raises(ValueError):
        require_non_gpt_analysis_model(name, setting="test")
    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "1")
    assert require_non_gpt_analysis_model(name, setting="test") == name
    assert not eligible_model("gpt-image-2")


def test_alias_and_malformed_permissions_fail_closed(monkeypatch):
    monkeypatch.delenv("CROW_ANALYSIS_ALLOW_GPT", raising=False)
    monkeypatch.setenv("FAPAI_ANALYSIS_ALLOW_GPT", "1")
    assert gpt_models_enabled()
    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "0")
    with pytest.raises(ValueError):
        gpt_models_enabled()
    assert not eligible_model("gpt-6.1-sol")
    monkeypatch.delenv("FAPAI_ANALYSIS_ALLOW_GPT")
    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "maybe")
    with pytest.raises(ValueError):
        gpt_models_enabled()


def test_settings_explicit_boolean_roundtrip_does_not_follow_server_environment(
    monkeypatch,
):
    model = model_fixture()
    old = config_fixture()
    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "1")
    for bad in ("true", 1, None):
        with pytest.raises(RestartError):
            validate({**old, "ai": {**old["ai"], "allow_gpt": bad}})
    off = {**old, "ai": {**old["ai"], "allow_gpt": False, "reasoning_effort": "none"}}
    assert validate(off) == old
    new = {
        **old,
        "ai": {
            **old["ai"],
            "model": "gpt-6.1-sol",
            "allow_gpt": True,
            "reasoning_effort": "low",
        },
    }
    assert inventory(render(model, new))["effective"] == new
    env = render(model, new)["services"]["pc2-analysis-1"]["environment"]
    assert env["CROW_ANALYSIS_ALLOW_GPT"] == env["FAPAI_ANALYSIS_ALLOW_GPT"] == "1"
    assert env["OPENAI_REASONING_EFFORT"] == "low"
    restored = render(render(model, new), old)
    assert inventory(restored)["effective"] == old
    assert (
        restored["services"]["pc2-analysis-1"]["environment"]["CROW_ANALYSIS_ALLOW_GPT"]
        == "0"
    )
    disabled = {**new, "ai": {**new["ai"], "allow_gpt": False}}
    normalized = validate(disabled)
    assert normalized["ai"]["model"] == "gpt-6.1-sol"
    assert "allow_gpt" not in normalized["ai"]
    assert inventory(render(render(model, new), disabled))["effective"] == normalized


def test_disabled_saved_gpt_preference_does_not_block_config_or_admit_requests(monkeypatch):
    from src.llm_openai_compatible import _get_openai_compatible_config

    monkeypatch.setenv("OPENAI_BASE_URL", "https://invalid.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "0")
    monkeypatch.delenv("FAPAI_ANALYSIS_ALLOW_GPT", raising=False)
    assert _get_openai_compatible_config()["model"] == "gpt-6.1-sol"
    assert not eligible_model("gpt-6.1-sol")
    with pytest.raises(ValueError):
        require_non_gpt_analysis_model("gpt-6.1-sol", setting="request")


def test_disabling_filters_existing_qualified_cache_and_live_pool(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("FAPAI_ANALYSIS_ALLOW_GPT", raising=False)
    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "1")
    pool = make_pool(tmp_path, {"gpt-6.1-sol": 5, "deepseek-fixture": 4})
    assert set(pool.ensure()) == {"gpt-6.1-sol", "deepseek-fixture"}
    assert pool.chat("business", model="gpt-6.1-sol") == "production"
    calls = list(pool.session.calls)
    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "0")
    assert pool.available() == ["deepseek-fixture"]
    second = QualifiedModelPool(pool.config, store=pool.store, session=pool.session)
    assert second.available() == ["deepseek-fixture"]
    for instance in (pool, second):
        with pytest.raises(LLMBackendUnavailableError):
            instance.request("gpt-6.1-sol", "business")
        with pytest.raises(LLMBackendUnavailableError):
            instance.chat("business", model="gpt-6.1-sol")
    assert pool.session.calls == calls
    assert pool.chat("business") == "production"


def test_cached_direct_request_cannot_outlive_disabled_permission(monkeypatch):
    from src.llm_openai_compatible import _chat_with_openai_compatible

    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "0")
    monkeypatch.delenv("FAPAI_ANALYSIS_ALLOW_GPT", raising=False)
    with pytest.raises(ValueError):
        _chat_with_openai_compatible(
            "business",
            {
                "base_url": "https://invalid.test",
                "api_key": "fake-key",
                "model": "gpt-6.1-sol",
                "max_retries": 1,
                "timeout": 1,
            },
        )


def test_enabling_a_preferred_gpt_route_resumes_discovery_without_resetting_budget(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("FAPAI_ANALYSIS_ALLOW_GPT", raising=False)
    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "0")
    pool = make_pool(tmp_path, {"gpt-6.1-sol": 5, "deepseek-fixture": 5})
    pool.config["models"] = ["deepseek-fixture"]
    assert pool.ensure() == ["deepseek-fixture"]
    assert pool.store.snapshot()["scan_complete"]
    key = pool.store.key
    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "1")
    pool.config["models"] = ["gpt-6.1-sol"]
    assert not pool._scan_complete(pool.store.snapshot())
    pool.store.change(lambda state: state.update(next_scan=0))
    assert "gpt-6.1-sol" in pool.ensure()
    assert pool.store.key == key


def test_gpt_settings_mailbox_claim_receipt_roundtrip(tmp_path):
    from src.collection_settings_store import SettingsStore

    store = SettingsStore(tmp_path)
    store.poll({"effective": config_fixture(), "api_key_configured": True})
    config = config_fixture()
    config["ai"].update(model="gpt-6.1-sol", allow_gpt=True, reasoning_effort="low")
    store.apply(
        {
            "request_id": "settings-gpt-optin-0001",
            "expected_revision": 0,
            "config": config,
            "api_key": None,
        }
    )
    command = store.poll({"effective": config_fixture(), "api_key_configured": True})[
        "command"
    ]
    assert command["config"] == config
    result = store.finish(
        {
            "request_id": command["request_id"],
            "claim": command["claim"],
            "result": "applied",
            "effective": config,
            "api_key_configured": True,
        }
    )
    assert result["request"]["status"] == "succeeded"
    assert store.status()["effective"] == config


def test_disabled_gpt_preference_falls_back_to_non_gpt_in_direct_chat_and_preflight(
    monkeypatch,
):
    import requests as req_mod

    from src.llm_openai_compatible import (
        _chat_with_openai_compatible,
        preflight_openai_compatible_backend,
    )

    called_models: list[str] = []

    class FakeResponse:
        def __init__(self, status_code: int, text: str = '{"choices":[{"message":{"content":"{\\"ok\\":true}"}}]}'):
            self.status_code = status_code
            self.text = text
            self.content = text.encode("utf-8")

        def json(self):
            import json

            return json.loads(self.text)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise req_mod.HTTPError(f"HTTP {self.status_code}", response=self)

    class FakeSession(req_mod.sessions.Session):
        def get(self, *_a, **_k):
            return FakeResponse(200, '{"data":[]}')

        def post(self, _url, *, json, **_k):
            called_models.append(json["model"])
            return FakeResponse(200)

    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "0")
    monkeypatch.delenv("FAPAI_ANALYSIS_ALLOW_GPT", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    monkeypatch.setenv("OPENAI_MODEL_CANDIDATES", "gpt-6.1-sol,deepseek-fixture")
    monkeypatch.setattr(req_mod, "Session", FakeSession)

    reply = _chat_with_openai_compatible(
        "business",
        {
            "base_url": "https://example.test/v1",
            "api_key": "test-key",
            "model": "gpt-6.1-sol",
            "models": ["gpt-6.1-sol", "deepseek-fixture"],
            "max_retries": 2,
            "timeout": 5,
        },
    )
    assert reply == '{"ok":true}'
    assert called_models == ["deepseek-fixture"]

    called_models.clear()
    preflight = preflight_openai_compatible_backend(timeout=5, check_chat=True)
    assert preflight["chat_status_code"] == 200
    assert preflight["chat_model_name"] == "deepseek-fixture"
    assert called_models == ["deepseek-fixture"]


def test_empty_allowed_model_pool_returns_non_retryable_policy_status(
    tmp_path, monkeypatch
):
    from src.llm_openai_compatible import preflight_openai_compatible_backend
    from tools.detail_worker_config import (
        _llm_preflight_is_retryable,
        _llm_preflight_is_unavailable,
    )

    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "0")
    monkeypatch.delenv("FAPAI_ANALYSIS_ALLOW_GPT", raising=False)
    monkeypatch.setenv("CROW_ANALYSIS_MODEL_POOL_ENABLED", "1")
    monkeypatch.setenv("CROW_ANALYSIS_MODEL_POOL_PATH", str(tmp_path / "pool.sqlite3"))
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    monkeypatch.setenv("OPENAI_MODEL_CANDIDATES", "gpt-6.1-sol")

    preflight = preflight_openai_compatible_backend(timeout=5, check_chat=True)
    assert preflight["status_code"] == 403
    assert preflight["chat_status_code"] == 403
    assert preflight["model_pool"] == "no_eligible_models"
    assert preflight["reason"] == "no_eligible_analysis_models"
    assert _llm_preflight_is_unavailable(preflight) is True
    assert _llm_preflight_is_retryable(preflight) is False
