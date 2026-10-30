"""A deferred post-input document must survive actual owned-target cleanup."""

from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveBudget
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_solve_loading_transition import (
    AUTHENTICATED,
    FAILED,
    LOADING,
    SLIDER,
    TARGET,
    solve_probe,
)

PROBE_FAILED = {"probeFailed": True}
FOREIGN = {
    "readyState": "complete",
    "hasSlider": True,
    "href": TARGET.replace("123", "456"),
}
BLANK = {"readyState": "complete", "href": TARGET}
CASES = [
    ("post_drag", [PROBE_FAILED], "cdp_unavailable"),
    ("post_drag", [LOADING], "challenge_loading"),
    ("post_drag", [LOADING, PROBE_FAILED], "cdp_unavailable"),
    ("post_drag", [LOADING, FOREIGN], "slider_not_found"),
    ("retry_after_drag", [PROBE_FAILED], "cdp_unavailable"),
    ("retry_after_drag", [LOADING], "challenge_loading"),
    ("retry_after_drag", [LOADING, PROBE_FAILED], "cdp_unavailable"),
    ("retry_after_drag", [FOREIGN], "slider_not_found"),
    ("retry_after_drag", [BLANK], "slider_not_found"),
    ("retry_before_drag", [PROBE_FAILED], "cdp_unavailable"),
    ("retry_before_drag", [LOADING], "challenge_loading"),
    ("retry_before_drag", [LOADING, PROBE_FAILED], "cdp_unavailable"),
]


def owned_probe(monkeypatch, stage, after, *, owned=True, local_mock=False):
    summaries = (
        [FAILED, *after]
        if stage == "retry_after_drag"
        else ([{"hardBlock": True}, *after] if stage == "retry_before_drag" else after)
    )
    solver, clock, reads, waits = solve_probe(
        monkeypatch, summaries, sliders=[] if stage == "retry_before_drag" else [SLIDER]
    )
    budget = SolveBudget(deadline=100, clock=lambda: clock[0])
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_: budget)
    solver._wait_for_verification_success.return_value = False
    solver._is_local_mock_slider_target = Mock(return_value=local_mock)
    solver._do_drag_local_mock = Mock(return_value=1)
    solver._close_owned_target_tabs = CaptchaSolver._close_owned_target_tabs.__get__(
        solver
    )
    solver._close_cdp_target = Mock(return_value=True)
    solver.ws = Mock()
    solver._cdp_mouse_down = False
    if owned:
        solver._opened_target_ids.update({"owned", "owned-probe"})
        solver.target_id = "owned"
    return solver, budget, clock, reads, waits


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("stage,after,reason", CASES)
def test_deferred_post_input_document_is_not_closed(
    monkeypatch, stage, after, reason, owned
):
    solver, budget, _, _, waits = owned_probe(monkeypatch, stage, after, owned=owned)

    assert solver.solve(max_attempts=3, nc_retry_replay_limit=1) is False

    assert solver.last_failure_reason == reason
    solver._close_cdp_target.assert_not_called()
    assert solver._opened_target_ids == ({"owned", "owned-probe"} if owned else set())
    assert solver.target_id == ("owned" if owned else None)
    assert solver._do_drag.call_count == (0 if stage == "retry_before_drag" else 1)
    assert solver._reset_failed_nc_challenge.call_count == (
        0 if stage == "post_drag" else 1
    )
    solver._reload_page.assert_not_called()
    solver._recover_authenticated_list_page.assert_not_called()
    assert solver.ws is None and not solver._cdp_mouse_down
    assert budget.deadline == 100 and budget.reason is None
    assert waits.count(0.25) <= 32
    assert not solver.lock.locked() and solver._solve_budget is None


@pytest.mark.parametrize(
    "stage", ["post_drag", "retry_after_drag", "retry_before_drag"]
)
@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
def test_deferred_cleanup_preserves_stop_priority(monkeypatch, stage, reason):
    solver, budget, clock, _, _ = owned_probe(monkeypatch, stage, [PROBE_FAILED])
    summary = solver._page_challenge_summary

    def stop_at_unknown_document():
        result = summary()
        if result.get("probeFailed"):
            if reason == "cancelled":
                budget.event.set()
            else:
                clock[0] = budget.deadline
        return result

    solver._page_challenge_summary = stop_at_unknown_document
    assert solver.solve(max_attempts=3, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == budget.reason == reason
    solver._close_cdp_target.assert_not_called()
    solver._reload_page.assert_not_called()
    assert solver._opened_target_ids == {"owned", "owned-probe"}
    assert not solver.lock.locked() and solver._solve_budget is None


def test_local_mock_probe_failure_keeps_existing_owned_cleanup(monkeypatch):
    solver, _, _, _, _ = owned_probe(
        monkeypatch, "post_drag", [PROBE_FAILED], local_mock=True
    )
    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "cdp_unavailable"
    assert solver._close_cdp_target.call_count == 2
    assert solver._opened_target_ids == set()
    solver._do_drag_local_mock.assert_called_once()
    solver._do_drag.assert_not_called()


@pytest.mark.parametrize(
    "stage", ["post_drag", "retry_after_drag", "retry_before_drag"]
)
def test_verified_document_keeps_existing_success_cleanup(monkeypatch, stage):
    solver, _, _, _, _ = owned_probe(monkeypatch, stage, [LOADING, AUTHENTICATED])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is True
    assert solver.last_failure_reason is None
    assert solver._close_cdp_target.call_count == 2
    assert solver._opened_target_ids == set()
    solver._reload_page.assert_not_called()


def test_explicit_retryable_rejection_keeps_existing_owned_cleanup(monkeypatch):
    solver, _, _, _, _ = owned_probe(monkeypatch, "post_drag", [FAILED])
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0) is False
    assert solver.last_failure_reason == "challenge_retry_exhausted"
    assert solver._close_cdp_target.call_count == 2
    assert solver._opened_target_ids == set()
    solver._reset_failed_nc_challenge.assert_not_called()
