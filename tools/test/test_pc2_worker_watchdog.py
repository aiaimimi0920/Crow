"""Offline worker recovery: exact identity, stale progress and bounded retries."""

import json
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools.pc2_collection_controller import step


class WorkerDocker:
    def __init__(self):
        self.now = 10000
        self.rows = {}
        self.heartbeats = {}
        self.restarts = []
        self.before_recheck = lambda: None
        for index, name in enumerate(
            ("pc2-browser-solver", "pc2-seed-1", "pc2-detail-1", "pc2-analysis-1")
        ):
            cid = str(index + 1) * 64
            self.rows[name] = {
                "Id": cid,
                "Name": "/fapaifang-" + name,
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": "fapaifang-pc2",
                        "com.docker.compose.service": name,
                    }
                },
                "State": {
                    "Running": True,
                    "Status": "running",
                    "StartedAt": "original",
                    "Health": {"Status": "unhealthy"},
                },
            }
            self.heartbeats[cid] = {
                "worker_id": name,
                "pid": 1,
                "stage": "detail_item",
                "updated_at_epoch": 1000,
                "observed_at_epoch": self.now,
                "stale_seconds": 900,
            }

    def __call__(self, args, **_):
        if args[0] == "ps":
            return " ".join(row["Id"] for row in self.rows.values())
        if args[0] == "inspect":
            if len(args) == 2:
                self.before_recheck()
            return json.dumps(
                [row for row in self.rows.values() if row["Id"] in args[1:]]
            )
        assert args[:3] == ["restart", "--time", "30"]
        self.restarts.append(args[3])
        return ""

    def probe(self, cid):
        result = deepcopy(self.heartbeats[cid])
        result["observed_at_epoch"] = self.now
        return result


def watcher(tmp_path, docker, **kwargs):
    from tools.pc2_worker_watchdog import WorkerWatchdog

    return WorkerWatchdog(
        tmp_path,
        runner=docker,
        probe=docker.probe,
        clock=lambda: docker.now,
        interval=0,
        **kwargs,
    )


def test_controller_worker_recovery_precedes_nas_and_browser_progress(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "tools.pc2_collection_controller.operation_lock", lambda _: nullcontext()
    )
    calls = []
    settings = SimpleNamespace(
        journal=tmp_path / "settings", step=lambda: calls.append("nas")
    )
    restart = SimpleNamespace(
        journal=tmp_path / "restart", step=lambda: calls.append("restart")
    )
    worker = SimpleNamespace(step=lambda: calls.append("worker") or "restart_requested")
    progress = SimpleNamespace(step=lambda: calls.append("progress"))
    step(
        tmp_path, settings, restart, progress_watchdog=progress, worker_watchdog=worker
    )
    assert calls == ["worker"]


@pytest.mark.parametrize("pending", ["settings", "restart", "release-operation.json"])
def test_unresolved_operations_prevent_worker_recovery(tmp_path, monkeypatch, pending):
    monkeypatch.setattr(
        "tools.pc2_collection_controller.operation_lock", lambda _: nullcontext()
    )
    (tmp_path / pending).write_text("{}", encoding="utf-8")
    calls = []
    settings = SimpleNamespace(journal=tmp_path / "settings", step=lambda: None)
    restart = SimpleNamespace(journal=tmp_path / "restart", step=lambda: None)
    worker = SimpleNamespace(step=lambda: calls.append("worker"))
    if pending.startswith("release"):
        from tools.pc2_engine_controller import ControllerError

        with pytest.raises(ControllerError):
            step(tmp_path, settings, restart, worker_watchdog=worker)
    else:
        step(tmp_path, settings, restart, worker_watchdog=worker)
    assert calls == []


def test_stale_worker_restarts_after_grace_without_touching_browser(tmp_path):
    docker = WorkerDocker()
    w = watcher(tmp_path, docker)
    assert w.step() == "watching"
    docker.now += 119
    assert w.step() == "watching"
    docker.now += 1
    assert w.step() == "restart_requested"
    assert docker.restarts == [docker.rows["pc2-analysis-1"]["Id"]]
    receipt = json.loads(w.path.read_text())
    assert receipt["result"] == "restart_requested"
    assert receipt["restart_times"] == [docker.now]


@pytest.mark.parametrize(
    "health,running", [("healthy", True), ("starting", True), ("unhealthy", False)]
)
def test_healthy_starting_and_stopped_workers_are_not_restarted(
    tmp_path, health, running
):
    docker = WorkerDocker()
    for row in docker.rows.values():
        row["State"]["Health"]["Status"] = health
        row["State"]["Running"] = running
    watcher(tmp_path, docker, grace=0).step()
    assert not docker.restarts


@pytest.mark.parametrize(
    "change",
    [
        {"updated_at_epoch": 9990},
        {"updated_at_epoch": 11000},
        {"updated_at_epoch": float("nan")},
        {"pid": True},
        {"worker_id": "wrong-worker"},
        {"stage": "stopped"},
        {"stale_seconds": -1},
        {"stale_seconds": 20000},
    ],
)
def test_no_restart_without_valid_matching_stale_heartbeat(tmp_path, change):
    docker = WorkerDocker()
    for heartbeat in docker.heartbeats.values():
        heartbeat.update(change)
    watcher(tmp_path, docker, grace=0).step()
    assert not docker.restarts


@pytest.mark.parametrize("change", ["heartbeat", "start", "stopped", "healthy", "id"])
def test_recheck_rejects_recovered_or_replaced_target(tmp_path, change):
    docker = WorkerDocker()
    row = docker.rows["pc2-analysis-1"]
    # Only one candidate, so another worker cannot obscure this assertion.
    docker.rows = {"pc2-analysis-1": row}

    def mutate():
        if change == "heartbeat":
            docker.heartbeats[row["Id"]]["updated_at_epoch"] = docker.now - 1
        elif change == "start":
            row["State"]["StartedAt"] = "new-start"
        elif change == "stopped":
            row["State"]["Running"] = False
        elif change == "healthy":
            row["State"]["Health"]["Status"] = "healthy"
        else:
            row["Id"] = "f" * 64

    # A single-row initial inventory is also an inspect of one ID.
    calls = [0]

    def on_inspect():
        calls[0] += 1
        if calls[0] == 2:
            mutate()

    docker.before_recheck = on_inspect
    watcher(tmp_path, docker, grace=0).step()
    assert not docker.restarts


def test_durable_cooldown_and_daily_cap_survive_controller_restart(tmp_path):
    docker = WorkerDocker()
    docker.rows = {"pc2-analysis-1": docker.rows["pc2-analysis-1"]}
    for delay in (0, 600, 1200):
        docker.now += delay
        assert watcher(tmp_path, docker, grace=0).step() == "restart_requested"
        assert watcher(tmp_path, docker, grace=0).step() in {
            "cooldown",
            "restart_limit_reached",
        }
    docker.now += 3600
    assert watcher(tmp_path, docker, grace=0).step() == "restart_limit_reached"
    assert len(docker.restarts) == 3


@pytest.mark.parametrize(
    "contents",
    [
        b'{"broken":',
        b"[]",
        b"\xff",
        b'{"restart_times": [true]}',
        b'{"restart_times": [NaN]}',
    ],
)
def test_invalid_receipt_is_preserved_and_fails_closed(tmp_path, contents):
    docker = WorkerDocker()
    docker.rows = {"pc2-analysis-1": docker.rows["pc2-analysis-1"]}
    path = tmp_path / "worker-watchdog-pc2-analysis-1.json"
    path.write_bytes(contents)
    assert watcher(tmp_path, docker, grace=0).step() == "state_unavailable"
    assert path.read_bytes() == contents
    assert not docker.restarts


def test_uncertain_restart_is_never_replayed(tmp_path):
    docker = WorkerDocker()
    docker.rows = {"pc2-analysis-1": docker.rows["pc2-analysis-1"]}
    w = watcher(tmp_path, docker, grace=0)

    def fail(args, **kwargs):
        if args[0] == "restart":
            raise OSError("synthetic uncertain Docker response")
        return docker(args, **kwargs)

    w.run = fail
    with pytest.raises(OSError):
        w.step()
    docker.now += 10000
    assert watcher(tmp_path, docker, grace=0).step() == "reconciliation_required"
    assert not docker.restarts


def test_stopped_backup_ignored_and_active_duplicate_rejected(tmp_path):
    docker = WorkerDocker()
    backup = deepcopy(docker.rows["pc2-detail-1"])
    backup.update(Id="f" * 64, Name=backup["Name"] + "-backup")
    backup["State"].update(Running=False, Status="exited")
    docker.rows["backup"] = backup
    assert watcher(tmp_path, docker, grace=0).step() == "restart_requested"
    backup["State"].update(Running=True, Status="running")
    with pytest.raises(ValueError):
        watcher(tmp_path, docker, grace=0).step()
