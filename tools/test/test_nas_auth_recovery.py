from __future__ import annotations

import json

from src.nas_auth_recovery import NasAuthRecoveryCoordinator


def _coordinator(tmp_path, **overrides):
    options = {
        "stall_seconds": 1800,
        "pc1_timeout_seconds": 1800,
        "pc2_timeout_seconds": 600,
        "verify_timeout_seconds": 600,
        "cooldown_seconds": 300,
    }
    options.update(overrides)
    return NasAuthRecoveryCoordinator(tmp_path / "auth-recovery.json", **options)


def test_stall_creates_one_durable_recovery_and_operator_pause_blocks_trigger(tmp_path):
    coordinator = _coordinator(tmp_path)
    coordinator.sample(100, 20, now=1000)
    before = coordinator.sample(100, 20, operator_paused=True, now=2900)
    assert before["active"] is None

    requested = coordinator.sample(100, 20, now=2901)
    active = requested["active"]
    assert active["status"] == "requested"
    assert active["baseline_captured_count"] == 100

    same = coordinator.sample(100, 20, now=3000)
    assert same["active"]["recovery_id"] == active["recovery_id"]

    restarted = _coordinator(tmp_path)
    assert (
        restarted.snapshot(now=3000)["active"]["recovery_id"] == active["recovery_id"]
    )


def test_explicit_unhealthy_auth_signal_triggers_before_general_stall(tmp_path):
    coordinator = _coordinator(tmp_path)
    coordinator.sample(100, 20, now=1000)

    before = coordinator.sample(
        100,
        20,
        recovery_signal="cookie_snapshot_candidate_unhealthy",
        recovery_signal_stall_seconds=300,
        now=1299,
    )
    assert before["active"] is None

    operator_blocked = coordinator.sample(
        100,
        20,
        operator_paused=True,
        recovery_signal="cookie_snapshot_candidate_unhealthy",
        recovery_signal_stall_seconds=300,
        now=1300,
    )
    assert operator_blocked["active"] is None

    requested = coordinator.sample(
        100,
        20,
        recovery_signal="cookie_snapshot_candidate_unhealthy",
        recovery_signal_stall_seconds=300,
        now=1301,
    )
    assert requested["active"]["status"] == "requested"
    assert (
        requested["active"]["trigger_reason"] == "cookie_snapshot_candidate_unhealthy"
    )


def test_two_coordinators_reload_under_file_lock_and_keep_one_generation(tmp_path):
    first = _coordinator(tmp_path)
    second = _coordinator(tmp_path)
    first.sample(10, 5, now=100)

    first_active = first.sample(10, 5, now=1901)["active"]
    second_active = second.sample(10, 5, now=1902)["active"]

    assert second_active["recovery_id"] == first_active["recovery_id"]


def test_pc1_to_pc2_flow_requires_matching_generation_and_progress_confirmation(
    tmp_path,
):
    coordinator = _coordinator(tmp_path)
    coordinator.sample(50, 10, now=100)
    active = coordinator.sample(50, 10, now=1901)["active"]
    recovery_id = active["recovery_id"]

    stale = coordinator.claim("pc1", "old-generation", "pc1", now=1902)
    assert stale["ok"] is False
    assert stale["stale_recovery"] is True

    assert coordinator.claim("pc1", recovery_id, "pc1", now=1902)["ok"] is True
    ready = coordinator.snapshot_ready(
        recovery_id,
        sha256="a" * 64,
        cookie_count=12,
        created_at_epoch=1903,
        now=1903,
    )
    assert ready["recovery"]["status"] == "snapshot_ready"
    assert ready["recovery"]["snapshot"] == {
        "sha256": "a" * 64,
        "cookie_count": 12,
        "created_at_epoch": 1903.0,
    }
    assert coordinator.claim("pc2", recovery_id, "pc2", now=1904)["ok"] is True
    assert coordinator.pc2_restarting(recovery_id, now=1905)["ok"] is True
    verifying = coordinator.result(recovery_id, success=True, now=1906)
    assert verifying["status"] == "verifying"
    assert coordinator.sample(50, 10, now=1907)["active"]["status"] == "verifying"

    completed = coordinator.sample(51, 9, now=1908)
    assert completed["active"] is None
    assert completed["last_result"]["status"] == "succeeded"
    assert completed["last_result"]["reason"] == "captured_count_advanced"


def test_timeout_enters_cooldown_and_does_not_immediately_retrigger(tmp_path):
    coordinator = _coordinator(tmp_path, pc1_timeout_seconds=10, cooldown_seconds=300)
    coordinator.sample(7, 3, now=10)
    active = coordinator.sample(7, 3, now=1811)["active"]
    assert active["status"] == "requested"

    expired = coordinator.sample(7, 3, now=1822)
    assert expired["active"] is None
    assert expired["last_result"]["reason"] == "requested_timeout"
    assert expired["cooldown_until_epoch"] == 2122

    still_cooling = coordinator.sample(7, 3, now=2000)
    assert still_cooling["active"] is None
    retriggered = coordinator.sample(7, 3, now=2122)
    assert retriggered["active"]["status"] == "requested"


def test_exhausted_solver_signal_respects_failed_recovery_cooldown(tmp_path):
    coordinator = _coordinator(
        tmp_path,
        pc1_timeout_seconds=10,
        cooldown_seconds=1800,
    )
    coordinator.sample(7, 3, now=10)
    assert coordinator.sample(7, 3, now=1811)["active"]["status"] == "requested"

    failed = coordinator.sample(7, 3, now=1822)
    assert failed["last_result"]["status"] == "failed"
    assert failed["cooldown_until_epoch"] == 3622

    still_cooling = coordinator.sample(
        7,
        3,
        recovery_signal="node_solver_retries_exhausted",
        recovery_signal_stall_seconds=300,
        now=2121,
    )
    assert still_cooling["active"] is None

    still_cooling = coordinator.sample(
        7,
        3,
        recovery_signal="node_solver_retries_exhausted",
        recovery_signal_stall_seconds=300,
        now=2122,
    )
    assert still_cooling["active"] is None
    retried = coordinator.sample(
        7,
        3,
        recovery_signal="node_solver_retries_exhausted",
        recovery_signal_stall_seconds=300,
        now=3622,
    )
    assert retried["active"]["status"] == "requested"
    assert retried["active"]["trigger_reason"] == "node_solver_retries_exhausted"


def test_stalled_detail_signal_respects_failed_recovery_cooldown(tmp_path):
    coordinator = _coordinator(
        tmp_path,
        pc1_timeout_seconds=10,
        cooldown_seconds=1800,
    )
    coordinator.sample(7, 3, now=10)
    assert coordinator.sample(7, 3, now=1811)["active"]["status"] == "requested"
    failed = coordinator.sample(7, 3, now=1822)
    assert failed["last_result"]["status"] == "failed"

    still_cooling = coordinator.sample(
        7,
        3,
        recovery_signal="detail_challenge_stalled",
        recovery_signal_stall_seconds=300,
        now=2121,
    )
    assert still_cooling["active"] is None

    still_cooling = coordinator.sample(
        7,
        3,
        recovery_signal="detail_challenge_stalled",
        recovery_signal_stall_seconds=300,
        now=2122,
    )
    assert still_cooling["active"] is None
    retried = coordinator.sample(
        7,
        3,
        recovery_signal="detail_challenge_stalled",
        recovery_signal_stall_seconds=300,
        now=3622,
    )
    assert retried["active"]["status"] == "requested"
    assert retried["active"]["trigger_reason"] == "detail_challenge_stalled"


def test_exhausted_solver_signal_does_not_bypass_cooldown_after_success(tmp_path):
    coordinator = _coordinator(tmp_path, cooldown_seconds=1800)
    coordinator.sample(7, 3, now=10)
    active = coordinator.sample(7, 3, now=1811)["active"]
    recovery_id = active["recovery_id"]
    coordinator.claim("pc1", recovery_id, "pc1", now=1812)
    coordinator.snapshot_ready(
        recovery_id,
        sha256="c" * 64,
        cookie_count=2,
        now=1813,
    )
    coordinator.claim("pc2", recovery_id, "pc2", now=1814)
    coordinator.pc2_restarting(recovery_id, now=1815)
    coordinator.result(recovery_id, success=True, now=1816)
    succeeded = coordinator.sample(8, 3, now=1817)
    assert succeeded["last_result"]["status"] == "succeeded"

    still_cooling = coordinator.sample(
        8,
        3,
        recovery_signal="node_solver_retries_exhausted",
        recovery_signal_stall_seconds=300,
        now=2117,
    )
    assert still_cooling["active"] is None


def test_new_stalled_detail_challenge_bypasses_success_cooldown_only_after_progress(
    tmp_path,
):
    coordinator = _coordinator(tmp_path, cooldown_seconds=1800)
    coordinator.sample(7, 3, now=10)
    active = coordinator.sample(7, 3, now=1811)["active"]
    recovery_id = active["recovery_id"]
    coordinator.claim("pc1", recovery_id, "pc1", now=1812)
    coordinator.snapshot_ready(
        recovery_id,
        sha256="d" * 64,
        cookie_count=2,
        now=1813,
    )
    coordinator.claim("pc2", recovery_id, "pc2", now=1814)
    coordinator.pc2_restarting(recovery_id, now=1815)
    coordinator.result(recovery_id, success=True, now=1816)
    succeeded = coordinator.sample(8, 3, now=1817)
    assert succeeded["last_result"]["captured_count"] == 8

    same_generation = coordinator.sample(
        8,
        3,
        recovery_signal="detail_challenge_stalled",
        recovery_signal_stall_seconds=300,
        now=2117,
    )
    assert same_generation["active"] is None

    coordinator.sample(9, 3, now=2118)
    new_challenge = coordinator.sample(
        9,
        3,
        recovery_signal="detail_challenge_stalled",
        recovery_signal_stall_seconds=300,
        now=2418,
    )
    assert new_challenge["active"]["status"] == "requested"
    assert new_challenge["active"]["trigger_reason"] == "detail_challenge_stalled"


def test_persisted_state_contains_metadata_but_no_cookie_values(tmp_path):
    coordinator = _coordinator(tmp_path)
    coordinator.sample(1, 1, now=1)
    recovery_id = coordinator.sample(1, 1, now=1802)["active"]["recovery_id"]
    coordinator.claim("pc1", recovery_id, "pc1", now=1803)
    coordinator.snapshot_ready(
        recovery_id,
        sha256="b" * 64,
        cookie_count=2,
        now=1804,
    )

    payload = json.loads((tmp_path / "auth-recovery.json").read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert "cookie_count" in serialized
    assert "cookie_value" not in serialized
    assert "cookies" not in payload["active"]
