"""Unverified native input is execution uncertainty, not a rejected document."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveBudget
from tools import pc2_solver_execution as execution
from tools import pc2_solver_loop_failure as failure
from tools import pc2_solver_retry_state as retry
from tools import pc2_solver_state_store as store
from tools.test.test_captcha_solve_loading_transition import SLIDER, solve_probe

REASONS = (
    "window_focus_failed",
    "mouse_drag_exception",
    "screen_mapping_exception",
    "screen_mapping_unavailable",
    "screen_mapping_unverified",
    "screen_mapping_target_changed",
    "os_cursor_position_unverified",
    "os_button_state_unverified",
)


def uncertain_solve(monkeypatch, reason):
    solver, clock, reads, waits = solve_probe(
        monkeypatch, [{}], sliders=[SLIDER, SLIDER]
    )
    budget = SolveBudget(deadline=100, clock=lambda: clock[0])
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_: budget)
    solver._os_mouse_enabled.return_value = True

    def unavailable(*_args, **_kwargs):
        solver.last_failure_reason = reason

    solver._do_drag_os = Mock(side_effect=unavailable)
    return solver, budget, clock, reads, waits


@pytest.mark.parametrize("attempts", [1, 3])
@pytest.mark.parametrize("reason", REASONS)
def test_uncertain_native_input_stops_without_refresh_or_more_input(
    monkeypatch, reason, attempts
):
    solver, budget, _, reads, waits = uncertain_solve(monkeypatch, reason)
    solver._close_solver_ws = Mock()
    assert solver.solve(max_attempts=attempts) is False
    assert solver.last_failure_reason == "execution_unavailable"
    assert budget.deadline == 100 and budget.reason is None
    assert len(waits) == 2 and reads == [0]
    solver._find_slider.assert_called_once()
    solver._do_drag_os.assert_called_once()
    solver._close_solver_ws.assert_called_once()
    for operation in (
        solver._do_drag,
        solver._reload_page,
        solver._wait_for_verification_success,
        solver._reset_failed_nc_challenge,
        solver._recover_authenticated_list_page,
        solver._send_cdp,
    ):
        operation.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
def test_stop_during_uncertain_native_input_retains_priority(monkeypatch, reason):
    solver, budget, clock, _, _ = uncertain_solve(
        monkeypatch, "os_button_state_unverified"
    )

    def stop(*_args, **_kwargs):
        solver.last_failure_reason = "os_button_state_unverified"
        if reason == "cancelled":
            budget.event.set()
        else:
            clock[0] = budget.deadline

    solver._do_drag_os.side_effect = stop
    assert solver.solve(max_attempts=3) is False
    assert solver.last_failure_reason == budget.reason == reason
    assert budget.deadline == 100
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


def test_real_solve_result_keeps_target_and_existing_failure_budget(
    monkeypatch, tmp_path
):
    solver, _, _, _, _ = uncertain_solve(monkeypatch, "os_button_state_unverified")
    monkeypatch.setattr(execution, "_solver_class", lambda: lambda **_: solver)
    monkeypatch.setattr(execution, "log_event", lambda _: None)
    monkeypatch.setattr("tools.pc2_solver_diagnostics.log_event", lambda _: None)
    drags = Mock()
    monkeypatch.setattr(execution, "record_failed_drags", drags)
    details = {}
    assert (
        execution.run_solver_local_with_deadline(
            "offline", solver.target_url, timeout_seconds=0, failure_details=details
        )
        is False
    )
    assert details == {"failure_reason": "execution_unavailable"}
    drags.assert_called_once_with("offline", 0, allow_open=False)
    monkeypatch.setattr(store, "FALLBACK_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(failure, "time", SimpleNamespace(time=lambda: 1000))
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 2)
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_SECONDS", 180)
    monkeypatch.setattr(failure, "manual_fallback_enabled", lambda: True)
    monkeypatch.setattr(failure, "FALLBACK_FAIL_THRESHOLD", 1)
    monkeypatch.setattr(failure, "FALLBACK_STALL_SECONDS", 0)
    monkeypatch.setattr(failure, "log_event", lambda _: None)
    operations = []
    for name in (
        "rotate_failed_challenge_target",
        "maybe_browse_reference_tabs",
        "_report_manual_captcha",
    ):
        operation = Mock()
        operations.append(operation)
        monkeypatch.setattr(failure, name, operation)
    state = store._default_fallback_state()
    state.update(slider_attempts=1, consecutive_failures=1)
    store._save_fallback_state(state)
    probe = {"_target_id": "original"}
    assert (
        failure.record_failed_attempt(
            "offline", "offline", solver.target_url, probe, **details
        )
        is probe
    )
    saved = store._load_fallback_state()
    assert saved["slider_attempts"] == saved["consecutive_failures"] == 2
    assert saved["solver_cooldown_until"] == 1180
    assert saved["slider_next_attempt_at"] is None
    for operation in operations:
        operation.assert_not_called()
