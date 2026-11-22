import json
import os
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools.collection_control_lock import operation_lock
from tools.pc2_collection_controller import RestartController, step
from tools.pc2_engine_controller import ControllerError, EngineController
from tools.pc2_settings_model import inventory, render
from tools.pc2_settings_release import rebase
from tools.test.collection_settings_fixtures import model_fixture
from tools.test.test_pc2_engine_controller import containers, output


def test_restart_receipt_survives_crash_and_never_replays(tmp_path):
    calls = []
    command = {"request_id": "restart-durable-fixture", "claim": "a" * 64, "action": "restart_collection_workers"}
    client = SimpleNamespace(post=lambda action, body: calls.append((action, body)) or {"command": command})
    def crash():
        raise SystemExit("synthetic crash")
    engine = SimpleNamespace(inspect=lambda: None, restart=crash)
    controller = RestartController(client, engine, tmp_path)
    with pytest.raises(SystemExit):
        controller.step()
    assert json.loads(controller.journal.read_text())["result"] == "controller_interrupted"
    RestartController(client, engine, tmp_path).step()
    assert [action for action, _ in calls] == ["poll", "result"]
    assert not controller.journal.exists()


@pytest.mark.skipif(os.name != "posix", reason="Host flock is Linux-only")
def test_release_and_controller_share_nonblocking_lock(tmp_path):
    tmp_path.chmod(0o700)
    with operation_lock(tmp_path):
        with pytest.raises(BlockingIOError):
            with operation_lock(tmp_path):
                pytest.fail("concurrent mutation permitted")
    (tmp_path / "release-operation.json").write_text("{}")
    with pytest.raises(ControllerError):
        step(tmp_path, None, None)


def test_scaled_restart_ignores_only_stopped_extras():
    rows = containers()
    rows[-1]["State"]["Running"] = False
    engine = EngineController(run=lambda args, **_: output(args, rows))
    assert len(engine.inspect()) == 7
    rows.append(deepcopy(rows[-1]))
    with pytest.raises(ControllerError):
        engine.inspect()


def test_release_rebase_keeps_settings_key_and_mounts_but_adopts_code():
    target = model_fixture()
    edited = inventory(target)["effective"]
    edited["workers"]["details"] = 2
    edited["intervals"]["analysis"] = 42
    active = render(target, edited, "synthetic-operator-key")
    for service in target["services"].values():
        service["image"] = "release:new"
    result = rebase(active, target)
    assert inventory(result)["effective"] == edited
    assert result["services"]["pc2-analysis-1"]["environment"]["OPENAI_API_KEY"] == "synthetic-operator-key"
    assert all(service["image"] == "release:new" for service in result["services"].values())
    assert rebase(active, target, True)["services"]["pc2-detail-1"] == active["services"]["pc2-detail-1"]
    target["services"]["pc2-detail-1"]["volumes"][0]["source"] = "/changed/data"
    with pytest.raises(ValueError):
        rebase(active, target)


def test_step_docker_cache_deduplicates_bulk_inventory_but_keeps_single_rechecks():
    from tools.pc2_collection_controller import StepDockerCache

    calls = []

    def fake_text(args, timeout=60):
        calls.append(tuple(args))
        return f"out-{len(calls)}"

    cache = StepDockerCache(text_runner=fake_text)
    assert cache.run_text(["ps", "-aq", "--filter", "x"]) == "out-1"
    assert cache.run_text(["ps", "-aq", "--filter", "x"]) == "out-1"
    assert cache.run_text(["inspect", "id1", "id2"]) == "out-2"
    assert cache.run_text(["inspect", "id1", "id2"]) == "out-2"
    # Single-container pre-restart identity rechecks must never be cached.
    assert cache.run_text(["inspect", "id1"]) == "out-3"
    assert cache.run_text(["inspect", "id1"]) == "out-4"
    # Any mutation invalidates cached inventory immediately.
    assert cache.run_text(["restart", "--time", "30", "id1"]) == "out-5"
    assert cache.run_text(["ps", "-aq", "--filter", "x"]) == "out-6"
