"""A deferred preflight must not authorize more input or slower fallbacks."""

from unittest.mock import Mock

import pytest

from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_preflight_loading import LOADING, preflight_probe

FAILED = {"readyState": "complete", "hardBlock": True, "explicitFailure": True}


def real_retry(solver, outcome):
    solver._reset_failed_nc_challenge = (
        CaptchaSolver._reset_failed_nc_challenge.__get__(solver)
    )
    solver._nc_retry_targets = Mock(
        return_value={"widget": {"x": 10, "y": 20, "width": 280, "height": 40}}
    )
    solver._click_css_point = Mock(return_value=True)
    solver._nc_retry_outcome = Mock(return_value=outcome)


@pytest.mark.parametrize(
    ("after", "outcome", "reason"),
    [
        (LOADING, {"loading": True}, "challenge_loading"),
        ({"probeFailed": True}, {"probeFailed": True}, "cdp_unavailable"),
    ],
)
def test_uncertain_immediate_reset_never_enters_another_retry_or_login_wait(
    monkeypatch, after, outcome, reason
):
    solver, _, _, _ = preflight_probe(monkeypatch, [FAILED, after])
    real_retry(solver, outcome)

    result = solver._preflight_current_challenge()

    assert not result["manual_required"] and not result["already_authenticated"]
    assert solver.last_failure_reason == reason
    solver._click_css_point.assert_called_once()
    solver._nc_retry_outcome.assert_called_once_with(timeout_seconds=3.0)
    solver._poll_until_authenticated.assert_not_called()
    solver._send_cdp.assert_not_called()


@pytest.mark.parametrize("kind", ["slider", "authenticated"])
@pytest.mark.parametrize("restored", [False, True])
def test_failed_reset_can_observe_loading_then_ready_without_more_input(
    monkeypatch, kind, restored
):
    ready = {"readyState": "complete", "hasSlider": kind == "slider"}
    ready["authenticatedPage"] = kind == "authenticated"
    solver, _, waits, _ = preflight_probe(monkeypatch, [FAILED, LOADING, ready])
    solver._reset_failed_nc_challenge.return_value = restored

    result = solver._preflight_current_challenge()

    assert result["has_slider"] is (kind == "slider")
    assert result["already_authenticated"] is (kind == "authenticated")
    assert solver.last_failure_reason is None
    assert waits == [0.25]
    solver._reset_failed_nc_challenge.assert_called_once()
    solver._poll_until_authenticated.assert_not_called()
    solver._send_cdp.assert_not_called()


def test_hard_block_wait_cannot_authorize_retry_on_a_new_loading_document(monkeypatch):
    solver, _, _, _ = preflight_probe(
        monkeypatch, [{"hardBlock": True, "readyState": "complete"}, LOADING]
    )

    result = solver._preflight_current_challenge()

    assert not result["manual_required"]
    assert solver.last_failure_reason == "challenge_loading"
    solver._poll_until_authenticated.assert_called_once()
    solver._reset_failed_nc_challenge.assert_not_called()


def test_cancelled_immediate_reset_stops_before_fresh_probe_or_login_wait(monkeypatch):
    solver, _, _, reads = preflight_probe(monkeypatch, [FAILED, LOADING])
    cancelled = [False]
    solver.cancel_checker = lambda: cancelled[0]

    def reset():
        cancelled[0] = True
        return False

    solver._reset_failed_nc_challenge.side_effect = reset
    result = solver._preflight_current_challenge()

    assert not result["manual_required"]
    assert solver.last_failure_reason == "cancelled" and reads[0] == 1
    solver._reset_failed_nc_challenge.assert_called_once()
    solver._poll_until_authenticated.assert_not_called()


@pytest.mark.parametrize(
    ("summary", "reason"),
    [(LOADING, "challenge_loading"), ({"probeFailed": True}, "cdp_unavailable")],
)
@pytest.mark.parametrize("headed", [False, True])
def test_full_solve_honors_deferred_preflight_before_all_fallbacks(
    monkeypatch, summary, reason, headed
):
    solver, _, _, _ = preflight_probe(monkeypatch, [summary])
    solver._headed_playwright_enabled = Mock(return_value=headed)
    solver._solve_with_ddddocr = Mock(return_value=False)
    solver._solve_with_playwright_stealth = Mock(return_value=False)
    solver._find_slider = Mock(return_value=None)
    solver._reload_page = Mock()
    solver._recover_authenticated_list_page = Mock(return_value=False)
    solver._bring_to_front = Mock()
    solver._close_owned_target_tabs = Mock()

    assert solver.solve(max_attempts=1) is False

    assert solver.last_failure_reason == reason
    solver.connect_tab.assert_called_once()
    solver._solve_with_ddddocr.assert_not_called()
    solver._solve_with_playwright_stealth.assert_not_called()
    solver._find_slider.assert_not_called()
    solver._reload_page.assert_not_called()
    solver._recover_authenticated_list_page.assert_not_called()
    solver._send_cdp.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
def test_retry_loading_grace_keeps_original_solve_stop_boundary(monkeypatch, reason):
    from src.captcha_budget import SolveBudget

    solver, clock, _, reads = preflight_probe(monkeypatch, [FAILED, LOADING])
    solver._close_owned_target_tabs = Mock()
    solver._find_slider = Mock()

    class ClockEvent:
        cancelled = False

        def is_set(self):
            return self.cancelled

        def wait(self, seconds):
            clock[0] += seconds
            self.cancelled = reason == "cancelled"

    event = ClockEvent()
    budget = SolveBudget(deadline=0.2, clock=lambda: clock[0], cancel_event=event)
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_kw: budget)

    def reset():
        solver._wait_interruptibly = CaptchaSolver._wait_interruptibly.__get__(solver)
        return False

    solver._reset_failed_nc_challenge.side_effect = reset

    assert solver.solve(max_attempts=1) is False

    assert solver.last_failure_reason == budget.reason == reason
    assert clock[0] <= 0.2 and reads[0] == 2
    solver._reset_failed_nc_challenge.assert_called_once()
    solver._find_slider.assert_not_called()
    solver._poll_until_authenticated.assert_not_called()
    solver._send_cdp.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None
