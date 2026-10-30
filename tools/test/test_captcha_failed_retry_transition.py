"""A failed retry click cannot classify a later document using stale failure state."""

from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_solve_loading_transition import (
    AUTHENTICATED,
    FAILED,
    LOADING,
    SLIDER,
    TARGET,
    solve_probe,
)


def failed_retry_probe(monkeypatch, after):
    solver, clock, reads, waits = solve_probe(
        monkeypatch, [FAILED, *after], sliders=[SLIDER]
    )
    solver._wait_for_verification_success.return_value = False
    return solver, clock, reads, waits


@pytest.mark.parametrize("loading", [False, True])
def test_failed_retry_can_finish_with_fresh_authenticated_proof(monkeypatch, loading):
    after = ([LOADING] if loading else []) + [AUTHENTICATED]
    solver, _, reads, waits = failed_retry_probe(monkeypatch, after)
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is True
    assert solver.last_failure_reason is None
    assert reads[0] == 2 + int(loading)
    assert (0.25 in waits) is loading
    solver._do_drag.assert_called_once()
    solver._reset_failed_nc_challenge.assert_called_once_with()
    solver._reload_page.assert_not_called()
    solver._send_cdp.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


def test_failed_retry_probe_error_is_not_a_site_rejection(monkeypatch):
    solver, _, reads, _ = failed_retry_probe(monkeypatch, [{"probeFailed": True}])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == "cdp_unavailable"
    assert reads[0] == 2
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


@pytest.mark.parametrize("loading_start", [0.0, 1.7849306759041876])
def test_failed_retry_still_loading_uses_existing_eight_second_grace(
    monkeypatch, loading_start
):
    solver, clock, reads, waits = failed_retry_probe(monkeypatch, [LOADING])

    def reset():
        clock[0] = loading_start
        waits.clear()
        return False

    solver._reset_failed_nc_challenge.side_effect = reset
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == "challenge_loading"
    assert waits == pytest.approx([0.25] * 32, rel=0, abs=1e-12)
    assert reads[0] == 33 and sum(waits) == pytest.approx(8.0, rel=0, abs=1e-12)
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


@pytest.mark.parametrize("after", [FAILED, {**FAILED, "retryableFailure": False}])
def test_still_failed_retry_keeps_original_terminal_classification(monkeypatch, after):
    solver, _, reads, _ = failed_retry_probe(monkeypatch, [after])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == (
        "challenge_retry_exhausted" if after["retryableFailure"] else "manual_required"
    )
    assert reads[0] == 2
    solver._do_drag.assert_called_once()
    solver._reset_failed_nc_challenge.assert_called_once_with()
    solver._reload_page.assert_not_called()


def test_late_slider_uses_one_existing_replay_and_fresh_geometry(monkeypatch):
    ready = {"readyState": "complete", "hasSlider": True, "href": TARGET}
    solver, _, _, _ = failed_retry_probe(monkeypatch, [LOADING, ready])
    solver._find_slider = Mock(side_effect=[SLIDER, {**SLIDER, "x": 80}])
    solver._wait_for_verification_success.side_effect = [False, True]
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is True
    assert solver._find_slider.call_count == solver._do_drag.call_count == 2
    assert solver._do_drag.call_args.args[0] == 101
    solver._reset_failed_nc_challenge.assert_called_once_with()
    solver._reload_page.assert_not_called()


@pytest.mark.parametrize("state", ["authenticated", "blank", "foreign", "error"])
def test_retry_recovery_keeps_actual_payload_and_target_validation(monkeypatch, state):
    from tools.test.test_captcha_dom_evaluation import DocumentSolver

    document = {
        "url": TARGET,
        "text": "auction evidence " * 12,
        "html": '<html><body><div id="J_StartPrice">123</div></body></html>',
    }
    if state == "blank":
        document["html"] = ""
    elif state == "foreign":
        document["url"] = TARGET.replace("123", "456")
    elif state == "error":
        document["text"] = "验证失败"
        document["nodes"] = [{"selectors": [".errloading"]}]
    ready = DocumentSolver(document, TARGET)._page_challenge_summary()
    solver, _, _, _ = failed_retry_probe(monkeypatch, [ready])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is (
        state == "authenticated"
    )
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


def test_foreign_late_slider_never_admits_an_extra_drag(monkeypatch):
    ready = {
        "readyState": "complete",
        "hasSlider": True,
        "href": TARGET.replace("123", "456"),
    }
    solver, _, _, _ = failed_retry_probe(monkeypatch, [ready])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == "slider_not_found"
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


def test_exhausted_replay_budget_never_starts_reset_or_new_probe(monkeypatch):
    solver, _, reads, _ = failed_retry_probe(monkeypatch, [AUTHENTICATED])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0) is False
    assert solver.last_failure_reason == "challenge_retry_exhausted"
    assert reads[0] == 1
    solver._reset_failed_nc_challenge.assert_not_called()


def test_cancelled_reset_never_starts_a_new_probe(monkeypatch):
    solver, _, reads, _ = failed_retry_probe(monkeypatch, [AUTHENTICATED])
    cancelled = [False]
    solver.cancel_checker = lambda: cancelled[0]

    def reset():
        cancelled[0] = True
        return False

    solver._reset_failed_nc_challenge.side_effect = reset
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == "cancelled" and reads[0] == 1


def test_cancel_during_retry_loading_grace_stops_without_a_late_probe(monkeypatch):
    solver, _, reads, _ = failed_retry_probe(monkeypatch, [LOADING, AUTHENTICATED])

    class CancelEvent:
        cancelled = False

        def is_set(self):
            return self.cancelled

        def wait(self, _seconds):
            self.cancelled = True

    event = CancelEvent()

    def reset():
        solver._wait_interruptibly = CaptchaSolver._wait_interruptibly.__get__(solver)
        return False

    solver._reset_failed_nc_challenge.side_effect = reset
    assert (
        solver.solve(max_attempts=1, nc_retry_replay_limit=1, cancel_event=event)
        is False
    )
    assert solver.last_failure_reason == "cancelled" and reads[0] == 2
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


def test_local_mock_keeps_original_retry_failure_contract(monkeypatch):
    solver, _, reads, _ = failed_retry_probe(monkeypatch, [AUTHENTICATED])
    solver._is_local_mock_slider_target = Mock(return_value=True)
    solver._do_drag_local_mock = Mock(return_value=1)
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == "manual_required" and reads[0] == 1
    solver._do_drag_local_mock.assert_called_once()
    solver._do_drag.assert_not_called()


def test_loading_grace_cannot_extend_the_original_solve_deadline(monkeypatch):
    solver, clock, _, _ = failed_retry_probe(monkeypatch, [LOADING])

    class ClockEvent:
        def is_set(self):
            return False

        def wait(self, seconds):
            clock[0] += seconds

    def reset():
        clock[0] = 99.6
        solver._wait_interruptibly = CaptchaSolver._wait_interruptibly.__get__(solver)
        return False

    solver._reset_failed_nc_challenge.side_effect = reset
    budget = SolveBudget(
        deadline=100, clock=lambda: clock[0], cancel_event=ClockEvent()
    )
    with pytest.raises(SolveStopped, match="deadline_exceeded"):
        solver._solve_attempts(max_attempts=1, nc_retry_replay_limit=1, _budget=budget)
    assert clock[0] == pytest.approx(100)
    assert solver.last_failure_reason == "deadline_exceeded"
    solver._do_drag.assert_called_once()
    assert not solver.lock.locked() and solver._solve_budget is None
