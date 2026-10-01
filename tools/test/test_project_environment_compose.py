"""Pure resolved Compose models: no Docker, services or real configuration files."""

from copy import deepcopy

import pytest

from src.project_environment import EnvironmentAliasConflict
from tools.pc2_settings_model import inventory, render
from tools.test.collection_settings_fixtures import model_fixture


def model_with_namespace(prefix):
    model = model_fixture()
    for service in model["services"].values():
        original = service.get("environment", {})
        rewritten = {}
        for key, value in original.items():
            if key.startswith("FAPAI_"):
                for namespace in ["FAPAI", "CROW"] if prefix == "BOTH" else [prefix]:
                    rewritten[namespace + key[5:]] = value
            else:
                rewritten[key] = value
        if "environment" in service:
            service["environment"] = rewritten
    return model


@pytest.mark.parametrize("prefix", ["FAPAI", "CROW", "BOTH"])
def test_model_inventory_is_scoped_and_unchanged_plan_is_identical(monkeypatch, prefix):
    monkeypatch.setenv("CROW_DETAIL_MAX_ATTEMPTS", "private-global-one")
    monkeypatch.setenv("FAPAI_DETAIL_MAX_ATTEMPTS", "private-global-two")
    model = model_with_namespace(prefix)
    original = deepcopy(model)
    config = inventory(model)["effective"]
    assert config == inventory(model_fixture())["effective"]
    assert render(model, config) == original == model


@pytest.mark.parametrize("prefix", ["FAPAI", "CROW", "BOTH"])
def test_changed_settings_sync_aliases_preserving_worker_identity_and_mounts(prefix):
    model = model_with_namespace(prefix)
    original = deepcopy(model)
    config = inventory(model)["effective"]
    config["intervals"]["details"] = 35
    config["workers"]["analysis"] = 5
    result = render(model, config)
    env = result["services"]["pc2-detail-1"]["environment"]
    assert (
        env["CROW_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS"]
        == env["FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS"]
        == "35"
    )
    new = result["services"]["pc2-analysis-5"]
    assert (
        new["environment"]["CROW_DETAIL_WORKER_ID"]
        == new["environment"]["FAPAI_DETAIL_WORKER_ID"]
        == "analysis-5"
    )
    assert (
        new["environment"]["CROW_OUTPUT_DIR"]
        == new["environment"]["FAPAI_OUTPUT_DIR"]
        == "/data/output/detail_analysis_worker_5"
    )
    assert new["volumes"] == original["services"]["pc2-analysis-1"]["volumes"]
    assert (
        result["services"]["pc2-browser-solver"]
        == original["services"]["pc2-browser-solver"]
    )
    assert inventory(result)["effective"] == config
    assert model == original


def test_explicit_alias_conflict_rejects_the_plan_without_mutating_input():
    model = model_fixture()
    env = model["services"]["pc2-detail-1"]["environment"]
    env["CROW_DETAIL_MAX_ATTEMPTS"] = "private-new"
    env["FAPAI_DETAIL_MAX_ATTEMPTS"] = "private-old"
    before = deepcopy(model)
    with pytest.raises(EnvironmentAliasConflict) as error:
        inventory(model)
    assert "private-" not in str(error.value)
    assert model == before
