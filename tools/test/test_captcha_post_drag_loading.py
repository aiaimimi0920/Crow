"""An in-flight post-drag navigation must not be reloaded as a failed attempt."""

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


def post_drag_probe(monkeypatch, after):
    solver, clock, reads, waits = solve_probe(
        monkeypatch, [LOADING, *after], sliders=[SLIDER]
    )
    solver._wait_for_verification_success.return_value = False
    return solver, clock, reads, waits


@pytest.mark.parametrize("replays", [0, 2])
def test_post_drag_loading_can_finish_without_reload_or_another_drag(
    monkeypatch, replays
):
    solver, _, reads, waits = post_drag_probe(monkeypatch, [AUTHENTICATED])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=replays) is True
    assert solver.last_failure_reason is None and reads[0] == 2
    assert waits.count(0.25) == 1
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()
    solver._reset_failed_nc_challenge.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


def test_loading_after_drag_has_the_existing_bounded_failure(monkeypatch):
    solver, _, reads, waits = post_drag_probe(monkeypatch, [LOADING])
    assert solver.solve(max_attempts=3, nc_retry_replay_limit=2) is False
    assert solver.last_failure_reason == "challenge_loading"
    assert waits.count(0.25) == 32 and reads[0] == 32
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


def test_loading_probe_failure_remains_transport_unavailable(monkeypatch):
    solver, _, reads, waits = post_drag_probe(monkeypatch, [{"probeFailed": True}])
    assert solver.solve(max_attempts=3) is False
    assert solver.last_failure_reason == "cdp_unavailable" and reads[0] == 2
    assert waits.count(0.25) == 1
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


def test_late_same_target_slider_uses_only_the_existing_replay(monkeypatch):
    ready = {"readyState": "complete", "hasSlider": True, "href": TARGET}
    solver, _, _, _ = post_drag_probe(monkeypatch, [ready])
    solver._find_slider = Mock(side_effect=[SLIDER, {**SLIDER, "x": 80}])
    solver._wait_for_verification_success.side_effect = [False, True]
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is True
    assert solver._do_drag.call_count == 2
    assert solver._do_drag.call_args.args[0] == 101
    solver._reload_page.assert_not_called()
    solver._reset_failed_nc_challenge.assert_not_called()


def test_loading_does_not_replenish_an_exhausted_replay_budget(monkeypatch):
    ready = {"readyState": "complete", "hasSlider": True, "href": TARGET}
    solver, _, _, _ = post_drag_probe(monkeypatch, [ready])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0) is False
    solver._do_drag.assert_called_once()
    solver._reset_failed_nc_challenge.assert_not_called()


def test_late_foreign_slider_does_not_authorize_an_extra_drag(monkeypatch):
    ready = {
        "readyState": "complete",
        "hasSlider": True,
        "href": TARGET.replace("123", "456"),
    }
    solver, _, _, _ = post_drag_probe(monkeypatch, [ready])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == "slider_not_found"
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


def test_explicit_rejection_after_loading_is_not_success(monkeypatch):
    solver, _, _, _ = post_drag_probe(
        monkeypatch, [{**FAILED, "readyState": "complete", "retryableFailure": False}]
    )
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0) is False
    assert solver.last_failure_reason == "manual_required"
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


def test_cancelled_loading_grace_never_reads_again_or_reloads(monkeypatch):
    solver, _, reads, _ = post_drag_probe(monkeypatch, [AUTHENTICATED])
    summary = solver._page_challenge_summary

    class CancelEvent:
        cancelled = False

        def is_set(self):
            return self.cancelled

        def wait(self, _seconds):
            self.cancelled = True

    def begin_loading(*, deadline=None):
        solver._wait_interruptibly = CaptchaSolver._wait_interruptibly.__get__(solver)
        return summary(deadline=deadline)

    solver._page_challenge_summary = begin_loading
    assert solver.solve(max_attempts=3, cancel_event=CancelEvent()) is False
    assert solver.last_failure_reason == "cancelled" and reads[0] == 1
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


def test_loading_wait_does_not_extend_the_original_solve_deadline(monkeypatch):
    solver, clock, _, _ = post_drag_probe(monkeypatch, [LOADING])
    summary = solver._page_challenge_summary

    class ClockEvent:
        def is_set(self):
            return False

        def wait(self, seconds):
            clock[0] += seconds

    def begin_loading(*, deadline=None):
        if clock[0] < 99:
            clock[0] = 99.6
            solver._wait_interruptibly = CaptchaSolver._wait_interruptibly.__get__(
                solver
            )
        return summary(deadline=deadline)

    solver._page_challenge_summary = begin_loading
    budget = SolveBudget(
        deadline=100, clock=lambda: clock[0], cancel_event=ClockEvent()
    )
    with pytest.raises(SolveStopped, match="deadline_exceeded"):
        solver._solve_attempts(max_attempts=1, _budget=budget)
    assert clock[0] == pytest.approx(100)
    assert solver.last_failure_reason == "deadline_exceeded"
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


@pytest.mark.parametrize("state", ["authenticated", "blank", "foreign", "error"])
def test_late_success_keeps_real_payload_and_target_validation(monkeypatch, state):
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
    solver, _, _, _ = post_drag_probe(monkeypatch, [ready])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0) is (
        state == "authenticated"
    )
    solver._do_drag.assert_called_once()


def test_local_mock_keeps_its_original_loading_contract(monkeypatch):
    solver, _, _, waits = post_drag_probe(monkeypatch, [AUTHENTICATED])
    solver._is_local_mock_slider_target = Mock(return_value=True)
    solver._do_drag_local_mock = Mock(return_value=1)
    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "max_attempts_exceeded"
    assert 0.25 not in waits
    solver._do_drag_local_mock.assert_called_once()
    solver._do_drag.assert_not_called()
