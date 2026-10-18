"""Offline collection must not turn old challenges into human interruptions."""

import sqlite3

import pytest

from src.collection_auth_demand import collection_workers_available
from src.collection_engine_restart import RestartMailbox
from src.nas_auth_recovery import NasAuthRecoveryCoordinator


@pytest.mark.parametrize(
    "age,allowed", [(0, True), (30, True), (31, False), (-1, False)]
)
def test_inspected_worker_lease_expires_without_shutdown_report(tmp_path, age, allowed):
    mailbox = RestartMailbox(tmp_path, now=lambda: 100)
    mailbox.poll()
    assert collection_workers_available(root=tmp_path, now=100 + age) is allowed


def test_missing_database_is_not_created_or_treated_as_live(tmp_path):
    assert not collection_workers_available(root=tmp_path, now=100)
    assert not (tmp_path / "control").exists()


def test_unknown_database_fails_closed(tmp_path):
    path = tmp_path / "control" / "pc2-engine-restart.sqlite3"
    path.parent.mkdir()
    with sqlite3.connect(path):
        pass
    assert not collection_workers_available(root=tmp_path, now=100)


def manager(tmp_path, demand):
    return NasAuthRecoveryCoordinator(
        tmp_path / "recovery.json",
        stall_seconds=1,
        cooldown_seconds=0,
        automatic_auth_allowed=demand,
    )


def test_solver_heartbeat_and_old_pending_are_not_worker_evidence(tmp_path):
    recovery = manager(tmp_path, lambda: False)
    recovery.register_stage_auth_pc2(now=100)
    recovery.sample(10, 20, now=100)
    state = recovery.sample(10, 20, now=102)
    assert state["pc2_stage_auth_ready"]
    assert not state["automatic_auth_allowed"]
    assert state["active"] is None


@pytest.mark.parametrize("boundary", ["snapshot", "claim", "restart"])
def test_queued_recovery_invalidated_at_each_delivery_boundary(tmp_path, boundary):
    live = [True]
    recovery = manager(tmp_path, lambda: live[0])
    recovery.sample(10, 20, now=100)
    rid = recovery.sample(10, 20, now=102)["active"]["recovery_id"]
    live[0] = False
    if boundary == "restart":
        recovery = manager(tmp_path, lambda: live[0])
    if boundary == "claim":
        assert not recovery.claim("pc1", rid, "pc1", now=103)["ok"]
    state = recovery.snapshot(now=103)
    assert state["active"] is None
    assert state["last_result"]["reason"] == "collectors_unavailable"
    live[0] = True
    assert not recovery.claim("pc1", rid, "pc1", now=104)["ok"]
    assert recovery.sample(10, 20, now=104)["active"]["recovery_id"] != rid


def test_claimed_automatic_recovery_is_cancelled_but_manual_is_preserved(tmp_path):
    live = [True]
    recovery = manager(tmp_path, lambda: live[0])
    recovery.sample(10, 20, now=100)
    rid = recovery.sample(10, 20, now=102)["active"]["recovery_id"]
    assert recovery.claim("pc1", rid, "pc1", now=103)["ok"]
    live[0] = False
    assert recovery.snapshot(now=104)["active"] is None
    manual = recovery.request_manual("a" * 32, now=105)["recovery"]
    assert recovery.snapshot(now=106)["active"]["recovery_id"] == manual["recovery_id"]


def test_provider_failure_never_allows_automatic_auth(tmp_path):
    def unavailable():
        raise OSError("offline")

    recovery = manager(tmp_path, unavailable)
    recovery.sample(10, 20, now=100)
    assert recovery.sample(10, 20, now=102)["active"] is None


def test_production_host_requires_worker_evidence_but_keeps_auth_pause(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace

    from src import collection_runtime_config as config

    adapter = config.collection_adapter_from_env(default="taobao_judicial")
    live = [False]
    monkeypatch.setattr(config, "collection_workers_available", lambda: live[0])
    host = config.create_collection_host(
        data_root=tmp_path,
        repository=SimpleNamespace(adapter=adapter),
        adapter=adapter,
    )
    try:
        assert not host.NAS_AUTH_RECOVERY.snapshot()["automatic_auth_allowed"]
        live[0] = True
        host.RUNTIME.control.reason = "manual_required"
        assert host.NAS_AUTH_RECOVERY.snapshot()["automatic_auth_allowed"]
        host.RUNTIME.control.reason = "operator"
        assert not host.NAS_AUTH_RECOVERY.snapshot()["automatic_auth_allowed"]
    finally:
        host.executor.shutdown(wait=True)
