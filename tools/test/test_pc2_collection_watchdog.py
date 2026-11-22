"""Offline process recovery boundaries: never touch real Docker or credentials."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools.pc2_collection_controller import step
from tools.pc2_collection_watchdog import CollectionWatchdog
from tools.pc2_engine_controller import ControllerError, EngineController
from tools.pc2_settings_runtime import SettingsRuntime
from tools.test.collection_settings_fixtures import FakeDocker
from tools.test.test_pc2_engine_controller import containers, output


def backup(row, *, running=False):
    row = deepcopy(row)
    row.update(Id="f" * 64, Name=row["Name"] + "-before-release")
    row["State"].update(Running=running, Status="running" if running else "exited")
    return row


def test_both_controllers_ignore_retained_backups_but_reject_live_duplicates(tmp_path):
    rows = containers()
    rows.insert(0, backup(rows[0]))
    engine = EngineController(run=lambda args, **_: output(args, rows))
    assert len(engine.inspect()) == 8
    rows[0]["State"]["Running"] = True
    with pytest.raises(ControllerError):
        engine.inspect()
    docker = FakeDocker()
    docker.rows["backup"] = backup(docker.rows["pc2-seed-1"])
    runtime = SettingsRuntime(tmp_path, [], runner=docker)
    assert runtime.snapshot()["effective"]["workers"] == {"links": 1, "details": 3, "analysis": 4}
    docker.rows["backup"]["State"]["Running"] = True
    with pytest.raises(ValueError):
        runtime.snapshot()


class BrowserDocker:
    def __init__(self):
        self.row = {"Id": "a" * 64, "Name": "/fapaifang-pc2-browser-solver",
                    "Config": {"Labels": {"com.docker.compose.project": "fapaifang-pc2",
                                          "com.docker.compose.service": "pc2-browser-solver"}},
                    "State": {"Running": True, "Status": "running", "StartedAt": "before",
                              "Health": {"Status": "unhealthy"}}}
        self.restarts = []

    def __call__(self, args, **_):
        if args[0] == "ps":
            return self.row["Id"]
        if args[0] == "inspect":
            return json.dumps([self.row])
        assert args[:3] == ["restart", "--time", "30"]
        self.restarts.append(args[3])
        return ""


def test_stuck_browser_restart_has_grace_exact_target_and_durable_cooldown(tmp_path):
    docker, now = BrowserDocker(), [1000]
    watcher = CollectionWatchdog(tmp_path, runner=docker, clock=lambda: now[0])
    assert watcher.step() == "waiting"
    now[0] += 119
    assert watcher.step() == "waiting"
    now[0] += 1
    assert watcher.step() == "restart_requested"
    assert docker.restarts == ["a" * 64]
    # Even a controller crash/restart cannot trigger a rapid restart loop.
    watcher = CollectionWatchdog(tmp_path, runner=docker, clock=lambda: now[0])
    watcher.step()
    now[0] += 120
    assert watcher.step() == "waiting"
    assert len(docker.restarts) == 1
    assert json.loads(watcher.path.read_text())["result"] == "restart_requested"


@pytest.mark.parametrize("state", ["healthy", "starting", "stopped"])
def test_healthy_starting_and_deliberately_stopped_containers_are_untouched(tmp_path, state):
    docker = BrowserDocker()
    docker.row["State"]["Health"]["Status"] = state
    if state == "stopped":
        docker.row["State"].update(Running=False, Status="exited")
    watcher = CollectionWatchdog(tmp_path, runner=docker, grace=0)
    assert watcher.step() == "healthy_or_stopped"
    assert not docker.restarts


def test_persistent_restart_limit_backoff_and_healthy_reset(tmp_path):
    docker, now = BrowserDocker(), [1000]
    make_watcher = lambda: CollectionWatchdog(tmp_path, runner=docker, clock=lambda: now[0], grace=0, cooldown=10, max_attempts=3)
    watcher = make_watcher()
    assert watcher.step() == "restart_requested"
    now[0] += 10
    assert make_watcher().step() == "restart_requested"
    now[0] += 10
    assert make_watcher().step() == "waiting"
    now[0] += 10
    assert make_watcher().step() == "restart_requested"
    docker.row["State"]["Health"]["Status"] = "starting"
    assert make_watcher().step() == "healthy_or_stopped"
    docker.row["State"]["Health"]["Status"] = "unhealthy"
    now[0] += 10000
    assert make_watcher().step() == "restart_limit_reached"
    assert len(docker.restarts) == 3
    assert json.loads(watcher.path.read_text())["alert"] == "manual_intervention_required"
    docker.row["State"]["Health"]["Status"] = "healthy"
    assert make_watcher().step() == "healthy_or_stopped"
    docker.row["State"]["Health"]["Status"] = "unhealthy"
    assert make_watcher().step() == "restart_requested"


def test_watchdog_recovers_locally_before_nas_poll_and_skips_unresolved_operations(tmp_path, monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setattr("tools.pc2_collection_controller.operation_lock", lambda _: nullcontext())
    calls = []
    def unavailable():
        calls.append("nas")
        raise OSError("offline fixture")
    settings = SimpleNamespace(step=unavailable, journal=tmp_path / "settings.json")
    restart = SimpleNamespace(step=unavailable, journal=tmp_path / "restart.json")
    watcher = SimpleNamespace(step=lambda: calls.append("watchdog"))
    with pytest.raises(OSError):
        step(tmp_path, settings, restart, watcher)
    assert calls == ["watchdog", "nas"]
    calls.clear()
    restart.journal.write_text("{}")
    with pytest.raises(OSError):
        step(tmp_path, settings, restart, watcher)
    assert calls == ["nas"]
