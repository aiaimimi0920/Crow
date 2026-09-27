"""Backend escalation must not hide a node's already scheduled cooldown."""

import pytest

from tools import pc2_local_solver as solver
from tools.test.pc2_loop_test_dependencies import patch_loop_dependency


@pytest.mark.parametrize(
    "until,blocked,reason,challenge,expected",
    [
        (
            1000,
            True,
            "repeated_solver_failures",
            "seed-one",
            "collection_resume_pending",
        ),
        (1100, True, "repeated_solver_failures", "seed-one", "solver_cooldown_active"),
        (1000, False, "manual_required", "seed-one", "waiting_for_manual_auth"),
        (1000, True, "repeated_solver_failures", "seed-new", "waiting_for_manual_auth"),
    ],
)
def test_scoped_cooldown_survives_manual_escalation(
    monkeypatch, until, blocked, reason, challenge, expected
):
    state = solver._default_fallback_state()
    state.update(
        {
            "challenge_id": "seed-one",
            "scope": "seed",
            "slider_attempts": 10,
            "solver_cooldown_until": until,
            "solver_cooldown_reason": "repeated_solver_failures",
            "node_solver_blocked_reported": True,
        }
    )
    status = {
        "paused": True,
        "running": False,
        "scopes": {
            "seed": {
                "scope": "seed",
                "challenge_id": challenge,
                "paused": True,
                "manual_required": True,
                "manual_only": True,
                "last_failure_reason": reason,
                "node_solver_blocked": blocked,
                "last_request": {
                    "target_url": "https://sf.taobao.com/list/1.htm",
                    "node_id": "pc2",
                },
            }
        },
    }
    events, resumed = [], []
    patch_loop_dependency(
        monkeypatch, "log_event", lambda event: events.append(event["kind"])
    )
    patch_loop_dependency(
        monkeypatch, "write_solver_heartbeat", lambda *_args, **_kwargs: None
    )
    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _: True)
    patch_loop_dependency(
        monkeypatch,
        "process_pending_control_actions",
        lambda **_kwargs: {
            "handled": False,
            "last_probe_target": None,
            "last_auth_confirmed_at": 0,
        },
    )
    patch_loop_dependency(monkeypatch, "read_solver_status", lambda _: status)
    patch_loop_dependency(
        monkeypatch, "compact_active_challenge_pages", lambda *_args: {}
    )
    patch_loop_dependency(
        monkeypatch, "reset_forced_solver_scopes", lambda _a, _b, value, _d: value
    )
    patch_loop_dependency(monkeypatch, "_load_fallback_state", lambda: state)
    patch_loop_dependency(monkeypatch, "_save_fallback_state", lambda _: None)
    patch_loop_dependency(
        monkeypatch,
        "_retry_pending_collection_resume",
        lambda *_args, **_kwargs: resumed.append(1) or {},
    )
    patch_loop_dependency(
        monkeypatch,
        "run_solver_local_with_deadline",
        lambda *_a, **_kw: pytest.fail("must not solve"),
    )
    monkeypatch.setattr(solver.time, "time", lambda: 1000.0)
    monkeypatch.setattr(
        solver.time, "sleep", lambda _: (_ for _ in ()).throw(SystemExit())
    )
    with pytest.raises(SystemExit):
        solver.local_solver_loop(poll_seconds=1, expected_node_id="pc2")
    assert expected in events
    assert bool(resumed) is (expected == "collection_resume_pending")
