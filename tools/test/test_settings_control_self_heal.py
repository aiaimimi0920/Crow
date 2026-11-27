"""Regression tests for Slice 4 control-plane rollback isolation, snapshot retry, and unknown reconciliation."""

from __future__ import annotations

from copy import deepcopy

import pytest

from src.collection_engine_restart import RestartError
from src.collection_settings_store import SettingsStore
from tools.pc2_docker_api import clone_payload
from tools.pc2_settings_controller import SettingsController
from tools.test.collection_settings_fixtures import config_fixture
from tools.test.test_pc2_settings_ai_runtime import ExactDocker, setup_runtime


def test_clone_payload_replaces_template_service_alias_and_label() -> None:
    docker = ExactDocker()
    row = deepcopy(next(r for r in docker.rows.values() if "analysis-1" in r["Name"]))
    row["Config"]["Hostname"] = row["Id"][:12]
    row["NetworkSettings"]["Networks"]["fixture"]["Aliases"] = [
        "worker",
        "pc2-analysis-1",
        row["Id"][:12],
    ]
    cloned = clone_payload(row, {"K": "V"}, service_name="pc2-analysis-2")
    assert cloned["Labels"]["com.docker.compose.service"] == "pc2-analysis-2"
    assert "Hostname" not in cloned
    assert cloned["NetworkingConfig"]["EndpointsConfig"]["fixture"]["Aliases"] == [
        "worker",
        "pc2-analysis-2",
    ]


def test_rollback_isolates_single_entry_failure_and_restores_remaining_workers(
    tmp_path,
) -> None:
    docker = ExactDocker()
    runtime, request = setup_runtime(tmp_path, docker)
    runtime.wait_ready = lambda _model: False
    original_action = docker.action
    failed_once = {"done": False}

    def flaky_rollback_action(identifier, action, body=None, **query):
        if (
            action == "rename"
            and "-settings-failed-" in query.get("name", "")
            and not failed_once["done"]
        ):
            failed_once["done"] = True
            raise RuntimeError("transient rename error on one failed candidate")
        return original_action(identifier, action, body, **query)

    docker.action = flaky_rollback_action
    assert runtime.apply(request) == "interrupted"
    running = [
        r for r in docker.rows.values() if r["State"].get("Running") and "analysis" in r["Name"]
    ]
    assert len(running) >= 1


def test_controller_retries_transient_post_apply_snapshot_error(tmp_path) -> None:
    effective = config_fixture()
    calls = {"snapshot": 0}
    delivered: list[dict[str, object]] = []

    class FakeRuntime:
        root = tmp_path

        def __init__(self) -> None:
            self.sleep = lambda _s: None

        def invalidate_cache(self) -> None:
            pass

        def snapshot(self) -> dict[str, object]:
            calls["snapshot"] += 1
            if calls["snapshot"] == 2:
                raise RuntimeError("transient docker inspect timeout")
            return {"effective": effective, "api_key_configured": True}

        def apply(self, _cmd: dict[str, object]) -> str:
            return "applied"

    class FakeClient:
        def post(self, endpoint: str, payload: dict[str, object]) -> dict[str, object]:
            if endpoint == "poll":
                return {
                    "command": {
                        "request_id": "settings-req-retry-0001",
                        "revision": 1,
                        "claim": "a" * 64,
                        "config": effective,
                        "previous": effective,
                        "api_key": None,
                    }
                }
            delivered.append(payload)
            return {"ok": True}

    controller = SettingsController(FakeClient(), FakeRuntime())
    controller.step()
    controller.step()
    assert delivered[0]["result"] == "applied"
    assert delivered[0]["effective"] == effective


def test_settings_store_reconciles_unknown_request_when_observed_matches(tmp_path) -> None:
    now = [0.0]
    store = SettingsStore(tmp_path, now=lambda: now[0])
    initial = config_fixture()
    target = deepcopy(initial)
    target["intervals"]["analysis"] = 19
    store.poll({"effective": initial, "api_key_configured": True})
    store.apply(
        {
            "request_id": "req-unknown-0001",
            "expected_revision": 0,
            "config": target,
            "api_key": None,
        }
    )
    store.poll({"effective": initial, "api_key_configured": True})
    now[0] = 901.0
    assert store.status()["request"]["status"] == "unknown"

    unrelated = deepcopy(initial)
    unrelated["intervals"]["links"] = 99
    with pytest.raises(RestartError):
        store.reconcile_unknown(
            {
                "request_id": "req-unknown-0001",
                "effective": unrelated,
                "api_key_configured": True,
            }
        )

    reconciled = store.reconcile_unknown(
        {
            "request_id": "req-unknown-0001",
            "effective": target,
            "api_key_configured": True,
        }
    )
    assert reconciled["request"]["status"] == "succeeded"
    assert store.status()["effective"] == target


def test_key_change_cannot_be_confirmed_from_public_inventory(tmp_path):
    now = [0]
    store = SettingsStore(tmp_path, now=lambda: now[0])
    before = config_fixture()
    after = deepcopy(before)
    after["intervals"]["analysis"] = 19
    observed = {"effective": before, "api_key_configured": True}
    store.poll(observed)
    store.apply(dict(request_id="req-secret-00001", expected_revision=0,
                     config=after, api_key="synthetic-test-key"))
    store.poll(observed)
    now[0] = 901
    with pytest.raises(RestartError, match="cannot distinguish"):
        store.reconcile_unknown(dict(request_id="req-secret-00001", effective=after, api_key_configured=True))
    assert store.status()["request"]["status"] == "unknown"
