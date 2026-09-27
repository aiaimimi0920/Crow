"""Native authentication freshness policy exercised through the public facade."""

from tools import pc2_local_solver, pc2_solver_auth


def test_recent_healthy_auth_snapshot_requires_fresh_completed_health(
    monkeypatch,
) -> None:
    monkeypatch.setattr(pc2_solver_auth, "RECENT_HEALTHY_AUTH_MAX_AGE_SECONDS", 300.0)
    status = {
        "last_status": "manual_auth_completed",
        "running": False,
        "manual_required": False,
        "force_unlock_flag_exists": False,
        "cookie_snapshot_refresh": {
            "status": "completed",
            "refreshed": True,
            "last_finished_at_epoch": 1000.0,
            "result": {"health": {"healthy": True}},
        },
    }

    assert pc2_local_solver._recent_healthy_auth_snapshot(status, now=1299.0) is True
    assert pc2_local_solver._recent_healthy_auth_snapshot(status, now=1301.0) is False
    status["last_status"] = "resumed_after_cooldown"
    assert pc2_local_solver._recent_healthy_auth_snapshot(status, now=1299.0) is True
    status["cookie_snapshot_refresh"]["result"]["health"]["healthy"] = False
    assert pc2_local_solver._recent_healthy_auth_snapshot(status, now=1100.0) is False


def test_post_auth_cdp_probe_grace_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(pc2_solver_auth, "POST_AUTH_CDP_PROBE_GRACE_SECONDS", 90.0)

    assert (
        pc2_local_solver._post_auth_cdp_probe_grace_active(1000.0, now=1090.0) is True
    )
    assert (
        pc2_local_solver._post_auth_cdp_probe_grace_active(1000.0, now=1090.1) is False
    )
    assert pc2_local_solver._post_auth_cdp_probe_grace_active(None, now=1000.0) is False


def test_post_auth_cdp_probe_default_window_is_three_minutes(monkeypatch) -> None:
    monkeypatch.setattr(pc2_solver_auth, "POST_AUTH_CDP_PROBE_GRACE_SECONDS", 180.0)

    assert (
        pc2_local_solver._post_auth_cdp_probe_grace_active(1000.0, now=1180.0) is True
    )
    assert (
        pc2_local_solver._post_auth_cdp_probe_grace_active(1000.0, now=1180.1) is False
    )
