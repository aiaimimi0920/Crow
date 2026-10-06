"""Do not spend a solver invocation before its existing document can finish loading."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import captcha_preflight
from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver

LOADING = {"readyState": "loading", "hasSlider": False, "hardBlock": True}


def preflight_probe(monkeypatch, summaries):
    solver = CaptchaSolver()
    clock = [0.0]
    waits = []
    calls = [0]
    monkeypatch.setattr(
        captcha_preflight,
        "time",
        SimpleNamespace(monotonic=lambda: clock[0]),
        raising=False,
    )

    def summary():
        value = summaries[min(calls[0], len(summaries) - 1)]
        calls[0] += 1
        return value.copy()

    def wait(seconds):
        waits.append(seconds)
        clock[0] += seconds

    solver.ws = SimpleNamespace(close=Mock())
    solver.connect_tab = Mock(return_value=True)
    solver._page_challenge_summary = summary
    solver._wait_interruptibly = wait
    solver._send_cdp = Mock(
        side_effect=AssertionError("No navigation or input allowed")
    )
    solver._poll_until_authenticated = Mock(return_value=False)
    solver._reset_failed_nc_challenge = Mock(return_value=False)
    return solver, clock, waits, calls


def test_loading_document_can_reach_slider_before_invocation_is_failed(monkeypatch):
    solver, clock, waits, calls = preflight_probe(
        monkeypatch, [LOADING, LOADING, {"readyState": "complete", "hasSlider": True}]
    )
    result = solver._preflight_current_challenge()
    assert result["connected"] and result["has_slider"]
    assert solver.last_failure_reason is None
    assert clock[0] == 0.5 and waits == [0.25, 0.25] and calls[0] == 3
    solver.connect_tab.assert_called_once_with()
    solver._send_cdp.assert_not_called()
    solver._reset_failed_nc_challenge.assert_not_called()


def test_loading_document_can_become_authenticated_without_input(monkeypatch):
    solver, clock, _, _ = preflight_probe(
        monkeypatch, [LOADING, {"readyState": "complete", "authenticatedPage": True}]
    )
    assert solver._preflight_current_challenge()["already_authenticated"]
    assert solver.last_failure_reason is None and clock[0] == 0.25
    solver._send_cdp.assert_not_called()


def test_never_ready_document_stops_at_bounded_loading_window(monkeypatch):
    solver, clock, waits, calls = preflight_probe(monkeypatch, [LOADING])
    result = solver._preflight_current_challenge()
    assert not result["connected"] and not result["manual_required"]
    assert solver.last_failure_reason == "challenge_loading"
    assert clock[0] == 8.0 and len(waits) == 32 and calls[0] == 33
    solver._send_cdp.assert_not_called()
    solver._poll_until_authenticated.assert_not_called()


def test_loading_probe_failure_remains_transport_failure_not_manual(monkeypatch):
    solver, clock, _, _ = preflight_probe(monkeypatch, [LOADING, {"probeFailed": True}])
    assert not solver._preflight_current_challenge()["manual_required"]
    assert solver.last_failure_reason == "cdp_unavailable" and clock[0] == 0.25


def test_visible_slider_does_not_wait_for_unrelated_loading_resources(monkeypatch):
    solver, clock, waits, _ = preflight_probe(
        monkeypatch, [{"readyState": "loading", "hasSlider": True}]
    )
    assert solver._preflight_current_challenge()["has_slider"]
    assert clock[0] == 0 and waits == []


def test_ready_login_page_still_requires_login_instead_of_being_accepted(monkeypatch):
    solver, _, _, _ = preflight_probe(
        monkeypatch, [LOADING, {"readyState": "complete", "loginRequired": True}]
    )
    assert solver._preflight_current_challenge()["manual_required"]
    assert solver.last_failure_reason == "manual_required"
    solver._poll_until_authenticated.assert_called_once_with()


def test_loading_wait_preserves_cooperative_cancellation(monkeypatch):
    solver, clock, waits, _ = preflight_probe(monkeypatch, [LOADING])
    solver.cancel_checker = lambda: True
    with pytest.raises(SolveStopped, match="cancelled"):
        solver._preflight_current_challenge()
    assert solver.last_failure_reason == "cancelled"
    assert clock[0] == 0 and waits == []
    solver._send_cdp.assert_not_called()


def test_loading_wait_cannot_extend_existing_solver_deadline(monkeypatch):
    solver, clock, _, _ = preflight_probe(monkeypatch, [LOADING])

    class ClockEvent:
        def is_set(self):
            return False

        def wait(self, seconds):
            clock[0] += seconds

    solver._solve_budget = SolveBudget(
        deadline=0.4, clock=lambda: clock[0], cancel_event=ClockEvent()
    )
    solver._wait_interruptibly = CaptchaSolver._wait_interruptibly.__get__(solver)
    with pytest.raises(SolveStopped, match="deadline_exceeded"):
        solver._preflight_current_challenge()
    assert clock[0] == pytest.approx(0.4)
    solver._send_cdp.assert_not_called()
