"""Scoped cooperative shutdown and recovery, fully offline."""

import json
from copy import deepcopy

import pytest

from tools.pc2_cooperative_detail_drain import CooperativeDetailDrain
from tools.test.cooperative_detail_drain_fixtures import FakeDetailDocker


def maintenance(docker, **kwargs):
    receipts = {}

    def persist(name, value):
        assert name not in receipts
        receipts[name] = deepcopy(value)

    drain = CooperativeDetailDrain(
        docker,
        docker.expected,
        persist,
        clock=docker.clock,
        sleep=docker.sleep,
        **kwargs,
    )
    return drain, receipts


def assert_restored(docker):
    for name, original in docker.original.items():
        current = docker.inspect(name)
        assert current["State"]["Running"]
        for field in ("Id", "Image", "Config", "HostConfig", "Mounts"):
            assert current[field] == original[field]
    assert all(
        action in {"update", "kill?signal=SIGTERM", "start"}
        for _, action, _ in docker.calls
    )


def test_drains_existing_items_before_body_then_restores_same_containers():
    docker = FakeDetailDocker()
    drain, receipts = maintenance(docker)
    with drain:
        drain.require_drained()
        assert docker.now == 2
        assert all(not docker.inspect(name)["State"]["Running"] for name in docker.rows)
    assert_restored(docker)
    assert len([call for call in docker.calls if call[1] == "kill?signal=SIGTERM"]) == 3
    assert len([call for call in docker.calls if call[1] == "start"]) == 3
    safe = json.dumps(
        {name: value for name, value in receipts.items() if ".safe." in name}
    )
    assert "PRIVATE_TEST_VALUE" not in safe


def test_body_failure_still_restores_workers_without_suppressing_original_error():
    docker = FakeDetailDocker()
    drain, receipts = maintenance(docker)
    with pytest.raises(ValueError, match="browser fixture failed"), drain:
        raise ValueError("browser fixture failed")
    assert_restored(docker)
    assert "dependent-workers.restored.safe.json" in receipts


def test_drain_timeout_does_not_enter_body_or_force_kill_and_recovers_late_exit():
    docker = FakeDetailDocker(finish_after=5)
    drain, receipts = maintenance(docker, drain_timeout=1, recovery_timeout=10)
    with pytest.raises(TimeoutError, match="no force stop"), drain:
        pytest.fail("A running capture must prevent browser mutation")
    assert_restored(docker)
    assert "dependent-workers.drained.safe.json" not in receipts


@pytest.mark.parametrize("n", [1, 2, 3])
def test_partial_policy_failure_restores_original_policies_without_signals(n):
    docker = FakeDetailDocker()
    docker.failures[(f"fapaifang-pc2-detail-{n}", "update")] = True
    drain, _ = maintenance(docker)
    with pytest.raises(RuntimeError, match="fixture operation"), drain:
        pytest.fail("Policy failure must prevent activation")
    assert_restored(docker)
    assert not any(
        "kill" in action or action == "start" for _, action, _ in docker.calls
    )


@pytest.mark.parametrize("n", [1, 2, 3])
def test_partial_signal_failure_recovers_every_target(n):
    docker = FakeDetailDocker()
    docker.failures[(f"fapaifang-pc2-detail-{n}", "kill?signal=SIGTERM")] = True
    drain, receipts = maintenance(docker, recovery_timeout=3)
    with pytest.raises(RuntimeError), drain:
        pytest.fail("Signal failure must prevent activation")
    # A failed signal is treated as uncertain, so an unchanged original process
    # cannot be advertised as recovered even when its configuration is restored.
    assert_restored(docker)
    assert "dependent-workers.recovery-incomplete.safe.json" in receipts


def test_nonzero_exit_prevents_body_and_restores_original_workers():
    docker = FakeDetailDocker(exit_code=1)
    drain, _ = maintenance(docker)
    with pytest.raises(RuntimeError, match="did not exit cleanly"), drain:
        pytest.fail("Unclean exit cannot authorize browser cutover")
    assert_restored(docker)


def test_never_finished_item_is_reported_incomplete_not_force_stopped():
    docker = FakeDetailDocker(finish_after=100)
    drain, receipts = maintenance(docker, drain_timeout=1, recovery_timeout=1)
    with pytest.raises(RuntimeError, match="recovery is incomplete"), drain:
        pytest.fail("Unfinished item must not authorize cutover")
    assert_restored(docker)
    assert "dependent-workers.recovery-incomplete.safe.json" in receipts
    assert not any(action == "start" for _, action, _ in docker.calls)


@pytest.mark.parametrize(
    "field,value",
    [("Id", "f" * 64), ("Image", "different-image"), ("Name", "/retained-backup")],
)
def test_changed_identity_is_rejected_before_any_mutation(field, value):
    docker = FakeDetailDocker()
    docker.rows["fapaifang-pc2-detail-2"][field] = value
    drain, _ = maintenance(docker)
    with pytest.raises(RuntimeError, match="identity changed"), drain:
        pytest.fail("An unexpected canonical target must never be stopped")
    assert docker.calls == []


def test_start_failure_does_not_skip_restoration_of_other_workers():
    docker = FakeDetailDocker()
    docker.failures[("fapaifang-pc2-detail-1", "start")] = True
    drain, receipts = maintenance(docker)
    with pytest.raises(RuntimeError, match="recovery is incomplete"), drain:
        pass
    assert docker.inspect("fapaifang-pc2-detail-2")["State"]["Running"]
    assert docker.inspect("fapaifang-pc2-detail-3")["State"]["Running"]
    assert receipts["dependent-workers.recovery-incomplete.safe.json"][
        "failed_targets"
    ] == ["fapaifang-pc2-detail-1"]


def test_policy_restore_failure_still_waits_for_other_late_items(monkeypatch):
    docker = FakeDetailDocker(finish_after=5)
    original_action = docker.action

    def action(identity, operation, body=None):
        if (
            identity == docker.expected["fapaifang-pc2-detail-1"]["id"]
            and operation == "update"
            and body["RestartPolicy"]["Name"] == "unless-stopped"
        ):
            raise RuntimeError("fixture policy recovery failure")
        return original_action(identity, operation, body)

    monkeypatch.setattr(docker, "action", action)
    drain, receipts = maintenance(docker, drain_timeout=1, recovery_timeout=10)
    with pytest.raises(RuntimeError, match="recovery is incomplete"), drain:
        pytest.fail("Unfinished items cannot authorize cutover")
    assert docker.now >= 5
    for n in (2, 3):
        row = docker.inspect(f"fapaifang-pc2-detail-{n}")
        assert row["State"]["Running"] and row["State"]["StartedAt"] == "restored"
    assert receipts["dependent-workers.recovery-incomplete.safe.json"][
        "failed_targets"
    ] == ["fapaifang-pc2-detail-1"]


def test_config_changed_during_maintenance_is_not_overwritten_or_started():
    docker = FakeDetailDocker()
    drain, receipts = maintenance(docker)
    with pytest.raises(RuntimeError, match="recovery is incomplete"), drain:
        docker.rows["fapaifang-pc2-detail-1"]["Config"]["Env"].append(
            "OTHER_OWNER_EDIT=preserve"
        )
    first = docker.inspect("fapaifang-pc2-detail-1")
    assert "OTHER_OWNER_EDIT=preserve" in first["Config"]["Env"]
    assert not first["State"]["Running"]
    assert docker.inspect("fapaifang-pc2-detail-2")["State"]["Running"]
    assert docker.inspect("fapaifang-pc2-detail-3")["State"]["Running"]
    assert "dependent-workers.recovery-incomplete.safe.json" in receipts


def test_final_guard_rejects_worker_started_during_maintenance():
    docker = FakeDetailDocker()
    drain, _ = maintenance(docker)
    with drain:
        docker.action(docker.expected["fapaifang-pc2-detail-2"]["id"], "start")
        with pytest.raises(RuntimeError, match="no longer valid"):
            drain.require_drained()
    assert_restored(docker)


def test_context_cannot_be_replayed():
    docker = FakeDetailDocker()
    drain, _ = maintenance(docker)
    with drain:
        pass
    calls = len(docker.calls)
    with pytest.raises(RuntimeError, match="cannot be replayed"), drain:
        pass
    assert len(docker.calls) == calls


@pytest.mark.parametrize(
    "field,value",
    [("ExitCode", 1), ("StartedAt", "another-process"), ("FinishedAt", "later")],
)
def test_final_guard_rejects_changed_exit_generation(field, value):
    docker = FakeDetailDocker()
    drain, _ = maintenance(docker)
    with drain:
        docker.rows["fapaifang-pc2-detail-2"]["State"][field] = value
        with pytest.raises(RuntimeError, match="no longer valid"):
            drain.require_drained()
    assert_restored(docker)


def test_docker_mount_order_does_not_change_storage_contract(monkeypatch):
    docker = FakeDetailDocker()
    for row in docker.rows.values():
        row["Mounts"].append(
            {"Source": "/fixture/secret", "Destination": "/secret", "RW": False}
        )
    original_inspect = docker.inspect
    calls = 0

    def inspect(name):
        nonlocal calls
        calls += 1
        row = original_inspect(name)
        if calls % 2:
            row["Mounts"].reverse()
        return row

    monkeypatch.setattr(docker, "inspect", inspect)
    drain, receipts = maintenance(docker)
    with drain:
        drain.require_drained()
    assert "dependent-workers.restored.safe.json" in receipts
    assert all(row["State"]["Running"] for row in docker.rows.values())


def test_real_mount_change_still_blocks_recovery():
    docker = FakeDetailDocker()
    drain, receipts = maintenance(docker)
    with pytest.raises(RuntimeError, match="recovery is incomplete"), drain:
        docker.rows["fapaifang-pc2-detail-1"]["Mounts"][0]["RW"] = False
        with pytest.raises(RuntimeError, match="no longer valid"):
            drain.require_drained()
    assert not docker.rows["fapaifang-pc2-detail-1"]["State"]["Running"]
    assert receipts["dependent-workers.recovery-incomplete.safe.json"][
        "failed_targets"
    ] == ["fapaifang-pc2-detail-1"]


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
def test_rejects_unbounded_or_invalid_maintenance_timeout(timeout):
    with pytest.raises(ValueError, match="finite positive"):
        maintenance(FakeDetailDocker(), drain_timeout=timeout)
