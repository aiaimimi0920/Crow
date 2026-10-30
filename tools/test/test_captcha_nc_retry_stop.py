"""Cancellation inside retry-loading waits retains the original solve budget."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import captcha_budget, captcha_nc_retry
from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_solve_loading_transition import (
    FAILED,
    LOADING,
    SLIDER,
    solve_probe,
)


@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
@pytest.mark.parametrize("public_entry", [False, True])
def test_stop_during_retry_loading_wait_never_starts_more_input(
    monkeypatch, reason, public_entry
):
    ready_retry = {**FAILED, "href": LOADING["href"], "readyState": "complete"}
    solver, clock, reads, _ = solve_probe(
        monkeypatch, [FAILED, ready_retry, LOADING], sliders=[SLIDER]
    )
    monkeypatch.setattr(
        captcha_nc_retry, "time", SimpleNamespace(time=lambda: clock[0])
    )
    solver._wait_for_verification_success.return_value = False
    solver._reset_failed_nc_challenge = (
        CaptchaSolver._reset_failed_nc_challenge.__get__(solver)
    )
    solver._click_css_point = Mock(return_value=True)

    class ClockEvent:
        armed = False
        cancelled = False

        def is_set(self):
            return self.cancelled

        def wait(self, seconds):
            clock[0] += seconds
            if self.armed and reason == "cancelled":
                self.cancelled = True

    event = ClockEvent()
    budget = SolveBudget(deadline=100, cancel_event=event, clock=lambda: clock[0])
    original_refresh = solver._refresh_challenge_summary

    def refresh(fallback):
        summary = original_refresh(fallback)
        if summary == ready_retry:
            return summary
        assert summary == LOADING
        assert solver._solve_budget is budget
        event.armed = True
        if reason == "deadline_exceeded":
            clock[0] = 99.95
        return summary

    def targets():
        solver._wait_interruptibly = CaptchaSolver._wait_interruptibly.__get__(solver)
        return {"widget": {"x": 10, "y": 20, "width": 280, "height": 40}}

    solver._refresh_challenge_summary = refresh
    solver._nc_retry_targets = targets

    if public_entry:
        monkeypatch.setattr(captcha_budget, "SolveBudget", lambda **_kwargs: budget)
        assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    else:
        with pytest.raises(SolveStopped, match=reason):
            solver._solve_attempts(
                max_attempts=1, nc_retry_replay_limit=1, _budget=budget
            )

    assert event.armed
    assert budget.deadline == 100
    assert budget.reason == solver.last_failure_reason == reason
    assert reads[0] == 3
    solver._click_css_point.assert_called_once()
    solver._do_drag.assert_called_once()
    solver._find_slider.assert_called_once()
    solver._reload_page.assert_not_called()
    solver._send_cdp.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None
