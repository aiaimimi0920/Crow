"""The daemon must not lose an owned pending page just because no slider is visible."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools import pc2_solver_loop as loop
from tools import pc2_solver_retry_state as retry
from tools.pc2_solver_state_store import _default_fallback_state
from tools.test.maintenance_deferral_fixtures import CDP
from tools.test.pc2_maintenance_budget_fixtures import TARGETS


@pytest.mark.parametrize(
    "generation_changed,scope_roundtrip", [(False, False), (True, False), (False, True)]
)
@pytest.mark.parametrize("owned_success", [False, True])
def test_two_polls_preserve_pending_identity_only_for_current_generation(
    monkeypatch, generation_changed, scope_roundtrip, owned_success
):
    class StopPoll(BaseException):
        pass

    state = _default_fallback_state()
    state.update(challenge_id="one", scope="detail")
    status = {
        "scope": "detail",
        "challenge_id": "one",
        "paused": True,
        "running": False,
        "manual_required": False,
        "last_request": {"node_id": "pc2", "target_url": TARGETS["detail"]},
    }
    pending = {
        "_target_id": "owned-pending",
        "_target_url": TARGETS["detail"],
        "_target_cdp_endpoint": CDP,
        "_challenge_id": "one",
        "_navigation_unconfirmed": True,
    }
    if owned_success:
        pending.pop("_navigation_unconfirmed")
        pending["_maintenance_owned"] = True
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    monkeypatch.setattr(loop, "hold_manual_window", lambda _: False)
    monkeypatch.setattr(loop, "prepare_solver_browser", lambda *_: None)
    monkeypatch.setattr(
        loop, "IdlePointer", lambda _: SimpleNamespace(tick=lambda *_: None)
    )
    monkeypatch.setattr(loop, "write_solver_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(loop, "log_event", lambda _: None)
    monkeypatch.setattr(loop, "read_solver_status", lambda _: deepcopy(status))
    monkeypatch.setattr(loop, "compact_active_challenge_pages", lambda *_: {})
    monkeypatch.setattr(
        loop, "reset_forced_solver_scopes", lambda _a, _b, value, _d: value
    )
    monkeypatch.setattr(loop, "_load_fallback_state", lambda: deepcopy(state))
    monkeypatch.setattr(loop, "_save_fallback_state", lambda value: state.update(value))
    monkeypatch.setattr(
        retry, "_save_fallback_state", lambda value: state.update(value)
    )
    monkeypatch.setattr(loop, "retry_blocked_report", lambda *_: None)
    monkeypatch.setattr(loop, "probe_requested_targets", lambda *_a, **_k: (None, ""))
    monkeypatch.setattr(
        loop,
        "process_pending_control_actions",
        lambda **kw: {
            "handled": False,
            "last_probe_target": kw["last_probe_target"],
            "last_auth_confirmed_at": 0,
        },
    )
    received = []

    def recover(*_args, **kwargs):
        received.append(deepcopy(kwargs.get("last_probe_target")))
        current = deepcopy(pending)
        current["_challenge_id"] = status["challenge_id"]
        current["_target_url"] = TARGETS[status["scope"]]
        return {
            "handled": True,
            "last_probe_target": current,
            "last_auth_confirmed_at": 0,
            "reset_probe_counter": True,
        }

    def sleep(_):
        if len(received) == (3 if scope_roundtrip else 2):
            raise StopPoll
        if scope_roundtrip:
            scope = "seed" if len(received) == 1 else "detail"
            status.update(
                scope=scope, challenge_id="seed-one" if scope == "seed" else "one"
            )
            status["last_request"]["target_url"] = TARGETS[scope]
        if generation_changed:
            status["challenge_id"] = "two"

    monkeypatch.setattr(loop, "recover_stale_pause", recover)
    monkeypatch.setattr(loop.time, "sleep", sleep)
    with pytest.raises(StopPoll):
        loop.local_solver_loop(cdp_endpoint=CDP, poll_seconds=1, expected_node_id="pc2")
    expected = (
        [None, None, pending]
        if scope_roundtrip
        else [None, None if generation_changed else pending]
    )
    assert received == expected
    assert state["slider_attempts"] == state["consecutive_failures"] == 0
