"""Discovery and old qualification records are not business authorization."""

import json
import time

import pytest

from src.llm_analysis_policy import require_non_gpt_analysis_model
from src.llm_model_selector import LLMBackendUnavailableError
from src.llm_qualification_pool import QualifiedModelPool
from src.llm_qualification_store import QualificationStore
from tools.test.test_llm_qualification_pool import make_pool

SOL = "gpt-6.1-sol"
LUNA = "gpt-6-luna"
OLD = ["gpt-6-sol", "gpt-5.6-sol", "gpt-5.6-luna", "gpt-6-astra", "gpt-5.6-terra"]


@pytest.fixture(autouse=True)
def optin(monkeypatch):
    monkeypatch.delenv("FAPAI_ANALYSIS_ALLOW_GPT", raising=False)
    monkeypatch.setenv("CROW_ANALYSIS_ALLOW_GPT", "1")


def configured_pool(tmp_path, allowed, catalog=None):
    return make_pool(
        tmp_path,
        dict.fromkeys(catalog or [SOL, LUNA, *OLD, "deepseek-fixture"], 5),
        model=allowed[0],
        models=allowed,
    )


def seed_history(pool):
    now = time.time()
    rows = {
        name: {"score": 5, "checked_at": now, "elapsed": 0.01, "blocked_until": 0}
        for name in pool.session.models
    }
    rows[SOL].update(score=4, elapsed=50)
    pool.store.change(
        lambda state: state.update(models=rows, route_cursor=999, scan_complete=True)
    )
    return rows


@pytest.mark.parametrize(
    "name",
    [*OLD, "gpt-6.1-luna", "gpt-unknown", "provider/gpt-6.1-sol", "codex-auto", "o3"],
)
def test_gpt_switch_allows_only_two_exact_ids(name):
    with pytest.raises(ValueError):
        require_non_gpt_analysis_model(name, setting="test")


def test_only_configured_primary_survives_better_historical_scores_and_cursor(tmp_path):
    pool = configured_pool(tmp_path, [SOL])
    history = seed_history(pool)
    before = pool.store.snapshot()
    peers = []
    for _ in range(4):
        store = QualificationStore(pool.config, pool.store.path)
        store.reserve_request_slot = lambda: 0
        peers.append(
            QualifiedModelPool(pool.config.copy(), store=store, session=pool.session)
        )
    for peer in peers:
        assert peer.available() == [SOL]
        assert peer.chat("synthetic evidence") == "production"
        assert peer.config["last_successful_model"] == SOL
    assert pool.session.calls == [SOL] * 4
    assert pool.store.snapshot() == before
    assert pool.store.snapshot()["models"] == history


def test_only_explicit_ordered_fallbacks_and_actual_model_metadata(tmp_path, caplog):
    pool = configured_pool(tmp_path, [SOL, LUNA, "deepseek-fixture"])
    seed_history(pool)
    assert pool.available() == [SOL, LUNA, "deepseek-fixture"]
    for _ in range(3):
        pool.chat("private fixture prompt")
    assert pool.session.calls == [SOL] * 3
    pool.session.failed.add(SOL)
    with caplog.at_level("INFO"):
        assert pool.chat("private fixture prompt") == "production"
    assert pool.session.calls[-2:] == [SOL, LUNA]
    assert pool.config["last_successful_model"] == LUNA
    assert "analysis_model_fallback_selected" in caplog.text
    assert "private fixture prompt" not in caplog.text
    assert pool.config["api_key"] not in caplog.text


def test_primary_failure_without_explicit_fallback_never_uses_history(tmp_path):
    pool = configured_pool(tmp_path, [SOL])
    seed_history(pool)
    pool.session.failed.add(SOL)
    with pytest.raises(LLMBackendUnavailableError, match="exhausted"):
        pool.chat("fixture")
    assert pool.session.calls == [SOL]
    assert pool.available() == []
    assert all(name in pool.store.snapshot()["models"] for name in OLD)


@pytest.mark.parametrize("probe", [True, False])
def test_generation_entry_rejects_unconfigured_and_old_models(tmp_path, probe):
    pool = configured_pool(tmp_path, [SOL])
    for name in [LUNA, *OLD, "deepseek-fixture"]:
        with pytest.raises(LLMBackendUnavailableError, match="excluded"):
            pool.request(name, "fixture", probe=probe)
    assert pool.session.calls == []


def test_background_qualifies_only_configured_models_not_the_catalog(tmp_path):
    pool = configured_pool(tmp_path, [SOL])
    assert pool.discover() == [SOL]
    assert pool.ensure() == [SOL]
    assert pool.session.calls == [SOL] * 5
    assert list(pool.store.snapshot()["models"]) == [SOL]
    assert pool.refresh_in_background() == [SOL]
    assert pool.session.calls == [SOL] * 5


def test_policy_change_preserves_legacy_state_shared_cooldown_and_identity(tmp_path):
    pool = configured_pool(tmp_path, [SOL, LUNA])
    seed_history(pool)
    key = pool.store.key
    pool.store.cool_down(3600)
    before = pool.store.snapshot()
    for _ in range(4):
        peer = configured_pool(tmp_path, [SOL])
        assert peer.store.key == key
        assert peer.available() == []
        assert peer.ensure() == []
        assert peer.store.snapshot() == before
        assert not peer.session.calls
    assert json.loads(json.dumps(before))["route_cursor"] == 999


def test_policy_is_rechecked_after_waiting_for_request_slot(tmp_path, monkeypatch):
    from src import llm_qualification_pool as module

    pool = configured_pool(tmp_path, [SOL, LUNA])
    delays = iter([0.01, 0])
    pool.store.reserve_request_slot = lambda: next(delays)
    monkeypatch.setattr(
        module, "wait_for_slot", lambda *_: pool.config.update(model=SOL, models=[SOL])
    )
    with pytest.raises(LLMBackendUnavailableError, match="excluded"):
        pool.request(LUNA, "fixture", probe=True)
    assert not pool.session.calls


def test_expired_primary_renews_even_when_fallback_and_old_scan_are_ready(tmp_path):
    pool = configured_pool(tmp_path, [SOL, LUNA])
    seed_history(pool)
    pool.store.change(
        lambda state: state["models"][SOL].update(checked_at=time.time() - 86401)
    )
    assert pool.available() == [LUNA]
    assert pool.ensure() == [SOL, LUNA]
    assert pool.session.calls == [SOL] * 5


def test_unknown_non_gpt_requires_explicit_configuration_too(tmp_path):
    pool = configured_pool(
        tmp_path, ["deepseek-fixture"], ["deepseek-fixture", "new-provider-route"]
    )
    assert pool.ensure() == ["deepseek-fixture"]
    assert pool.session.calls == ["deepseek-fixture"] * 5
    assert "new-provider-route" not in pool.store.snapshot()["models"]


def test_runtime_config_keeps_primary_then_explicit_order_without_catalog_expansion(
    monkeypatch,
):
    from src.llm_openai_compatible import _get_openai_compatible_config

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    monkeypatch.setenv("OPENAI_MODEL", SOL)
    monkeypatch.setenv("OPENAI_MODEL_CANDIDATES", f"{LUNA};{SOL},deepseek-fixture")
    assert _get_openai_compatible_config()["models"] == [SOL, LUNA, "deepseek-fixture"]
    monkeypatch.setenv("OPENAI_MODEL_CANDIDATES", "gpt-6-sol")
    with pytest.raises(ValueError):
        _get_openai_compatible_config()
