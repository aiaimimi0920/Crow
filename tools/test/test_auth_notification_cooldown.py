from concurrent.futures import ThreadPoolExecutor

import pytest

from src.nas_auth_recovery import NasAuthRecoveryCoordinator


@pytest.mark.parametrize(
    "signal,scope",
    [
        ("seed_challenge_stalled", "seed"),
        ("detail_challenge_stalled", "detail"),
        ("node_solver_retries_exhausted", "detail"),
    ],
)
def test_repeated_failure_reports_respect_durable_cooldown(tmp_path, signal, scope):
    path = tmp_path / "recovery.json"

    def coordinator():
        return NasAuthRecoveryCoordinator(
            path, stall_seconds=1, pc1_timeout_seconds=10, cooldown_seconds=1800
        )

    c = coordinator()
    c.sample(10, 5, now=100)
    first = c.sample(10, 5, now=102)["active"]["recovery_id"]
    expired = c.sample(10, 5, now=113)
    assert expired["last_result"]["status"] == "failed"
    deadline = expired["cooldown_until_epoch"]

    def report(now):
        return coordinator().sample(
            10,
            5,
            now=now,
            recovery_signal=signal,
            blocked_scopes=(scope,),
            recovery_signal_stall_seconds=300,
        )

    for now in (413, 713, deadline - 1):
        state = report(now)
        assert state["active"] is None
        assert state["last_result"]["recovery_id"] == first
        assert state["last_result"]["status"] == "failed"
        assert state["cooldown_until_epoch"] == deadline

    with ThreadPoolExecutor(max_workers=4) as pool:
        states = list(pool.map(report, [deadline] * 4))
    ids = {state["active"]["recovery_id"] for state in states}
    assert len(ids) == 1
    assert first not in ids
