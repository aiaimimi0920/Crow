"""Release returns to fresh arbitration, never directly to browser execution."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools import pc2_solver_auth_pending as pending
from tools import pc2_solver_loop as loop
from tools import pc2_solver_loop_control as control
from tools import pc2_solver_state_store as store
from tools.test.pc2_auth_pending_fixtures import CDP, NOW, TARGET, pending_case

__all__ = ["pending_case"]


def wire_control(monkeypatch, state):
    store._save_fallback_state(state)
    monkeypatch.setattr(control, "nas_auth_recovery_client_enabled", lambda: False)
    monkeypatch.setattr(control, "_retry_pending_collection_resume", lambda _a: {})
    monkeypatch.setattr(pending, "time", SimpleNamespace(time=lambda: NOW))


def test_pending_controller_relinquishes_without_ack_or_probe_reset(
    monkeypatch, pending_case
):
    state, _latest, events, _retry = pending_case
    wire_control(monkeypatch, state)
    monkeypatch.setattr(control, "log_event", events.append)
    probe = {"_target_id": "retained-page"}

    result = control.process_pending_control_actions(
        api_base_url="https://nas.test/api",
        cdp_endpoint=CDP,
        expected_node_id="pc2",
        poll_seconds=5,
        last_probe_target=probe,
        last_auth_confirmed_at=123,
    )

    assert result == {
        "handled": False,
        "reset_probe_counter": False,
        "last_probe_target": probe,
        "last_auth_confirmed_at": 123,
    }
    assert [event["kind"] for event in events] == ["auth_confirmation_wait_released"]
    assert store._load_fallback_state()["auth_complete_pending"] is False


@pytest.mark.parametrize(
    "fresh_gate",
    ["operator", "cooldown_reset", "completed_after_probe", "running_after_probe"],
)
def test_release_reenters_fresh_control_and_execution_guards(
    monkeypatch, pending_case, fresh_gate
):
    state, latest, events, _retry = pending_case
    if fresh_gate != "cooldown_reset":
        state.update(
            solver_cooldown_until=None,
            solver_cooldown_reason=None,
            slider_next_attempt_at=None,
            consecutive_failures=0,
        )
    wire_control(monkeypatch, state)
    initial = deepcopy(latest)
    initial["scopes"]["detail"]["force_reset_required"] = fresh_gate == "cooldown_reset"
    initial.update(
        scope="detail", paused=True, manual_required=False, manual_only=False
    )
    if fresh_gate == "operator":
        initial.update(operator_paused=True)
    final = deepcopy(initial)
    if fresh_gate == "completed_after_probe":
        final.update(
            running=False,
            paused=False,
            manual_required=False,
            challenge_id=None,
            last_status="manual_auth_completed",
            force_unlock_flag_exists=False,
        )
        final["scopes"]["detail"].update(
            challenge_id=None,
            paused=False,
            manual_required=False,
            running=False,
        )
        final["last_request"] = deepcopy(initial["scopes"]["detail"]["last_request"])
    elif fresh_gate == "running_after_probe":
        final["running"] = True
    reads = iter([initial, final])
    actions = []

    class StopPoll(BaseException):
        pass

    def stop(_delay):
        raise StopPoll

    def forbidden(*_a, **_kw):
        pytest.fail("fresh control gate must prevent browser mutation")

    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    monkeypatch.setattr(loop, "hold_manual_window", lambda _p: False)
    monkeypatch.setattr(loop, "prepare_solver_browser", lambda *_a: None)
    monkeypatch.setattr(loop, "IdlePointer", lambda _e: SimpleNamespace(tick=forbidden))
    monkeypatch.setattr(loop, "write_solver_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(loop, "read_solver_status", lambda _a: next(reads))
    monkeypatch.setattr(loop, "compact_active_challenge_pages", lambda *_a: {})
    monkeypatch.setattr(loop, "retry_blocked_report", lambda *_a: None)
    monkeypatch.setattr(loop, "log_event", events.append)
    monkeypatch.setattr(control, "log_event", events.append)
    monkeypatch.setattr(loop, "time", SimpleNamespace(time=lambda: NOW, sleep=stop))
    monkeypatch.setattr(control, "time", SimpleNamespace(time=lambda: NOW, sleep=stop))
    monkeypatch.setattr(control, "close_challenge_pages_for_scope", forbidden)
    monkeypatch.setattr(control, "notify_force_reset", forbidden)
    monkeypatch.setattr(loop, "run_solver_local_with_deadline", forbidden)
    monkeypatch.setattr(loop, "recover_stale_pause", forbidden)

    def probe(*_a, **_kw):
        actions.append("probe")
        return {"_target_id": "old-page"}, TARGET

    monkeypatch.setattr(loop, "probe_requested_targets", probe)
    with pytest.raises(StopPoll):
        loop.local_solver_loop(cdp_endpoint=CDP, expected_node_id="pc2")

    kinds = [event["kind"] for event in events]
    assert kinds[0] == "auth_confirmation_wait_released"
    assert "auth_complete_confirmed" not in kinds
    assert "loop_error" not in kinds
    saved = store._load_fallback_state()
    assert saved["auth_complete_pending"] is False
    assert saved["slider_attempts"] == state["slider_attempts"]
    if fresh_gate == "cooldown_reset":
        assert "scoped_challenge_force_reset_deferred" in kinds
        assert saved["solver_cooldown_until"] == state["solver_cooldown_until"]
    elif fresh_gate in {"completed_after_probe", "running_after_probe"}:
        assert actions == ["probe"]
        blocked = [
            event
            for event in events
            if event["kind"] == "local_solver_execution_blocked"
        ]
        assert blocked[-1]["reason"] == (
            "request_already_resolved"
            if fresh_gate == "completed_after_probe"
            else "nas_solver_running"
        )
    else:
        assert actions == []
