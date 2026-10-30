"""A fresh slider summary can confirm one missed geometry pass without reload."""

from threading import Event
from unittest.mock import Mock, call

import pytest

from src.captcha_budget import SolveBudget
from src.captcha_solver import CaptchaSolver
from tools import pc2_solver_diagnostics as diagnostics
from tools.test.test_captcha_solve_loading_transition import SLIDER, TARGET, solve_probe

SEED = "https://sf.taobao.com/list/1.htm?page=2&location_code=31"


def visible(target=TARGET, ready="complete", **extra):
    return {"href": target, "readyState": ready, "hasSlider": True, **extra}


@pytest.mark.parametrize("target", [TARGET, SEED])
@pytest.mark.parametrize("ready", ["interactive", "complete"])
def test_late_bound_slider_gets_one_geometry_confirmation_not_a_reload(
    monkeypatch, target, ready
):
    solver, _, reads, waits = solve_probe(
        monkeypatch, [visible(target, ready)], sliders=[None, SLIDER]
    )
    solver.target_url = target
    assert solver.solve(max_attempts=1, slider_find_max_retries=1) is True
    assert reads[0] == 1
    assert solver._find_slider.call_args_list == [
        call(max_retries=1, retry_delay=0),
        call(max_retries=1, retry_delay=0),
    ]
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()
    solver._reset_failed_nc_challenge.assert_not_called()
    assert 0.25 not in waits


@pytest.mark.parametrize("target", [TARGET, SEED])
@pytest.mark.parametrize("hard_block", [False, True])
def test_unconfirmed_slider_geometry_defers_without_reload_or_extra_attempts(
    monkeypatch, target, hard_block
):
    solver, _, reads, _ = solve_probe(
        monkeypatch, [visible(target, hardBlock=hard_block)]
    )
    solver.target_url = target
    solver._opened_target_ids.add("retained")
    assert solver.solve(max_attempts=5, nc_retry_replay_limit=2) is False
    assert solver.last_failure_reason == "slider_not_found"
    assert solver._find_slider.call_count == 2 and reads[0] == 1
    solver._reload_page.assert_not_called()
    solver._do_drag.assert_not_called()
    solver._reset_failed_nc_challenge.assert_not_called()
    solver._close_owned_target_tabs.assert_not_called()
    assert solver._opened_target_ids == {"retained"}
    assert solver._solve_budget is None and not solver.lock.locked()


@pytest.mark.parametrize(
    "target,current",
    [(TARGET, TARGET.replace("123", "456")), (SEED, SEED.replace("page=2", "page=3"))],
)
def test_foreign_slider_never_authorizes_a_confirmation_or_input(
    monkeypatch, target, current
):
    solver, _, _, _ = solve_probe(
        monkeypatch, [visible(current)], sliders=[None, SLIDER]
    )
    solver.target_url = target
    assert solver.solve(max_attempts=1, slider_find_max_retries=1) is False
    assert solver.last_failure_reason == "slider_not_found"
    solver._find_slider.assert_called_once_with(max_retries=1, retry_delay=0)
    solver._reload_page.assert_not_called()
    solver._do_drag.assert_not_called()


@pytest.mark.parametrize("stop", ["cancelled", "deadline_exceeded"])
def test_confirmation_obeys_the_same_cancel_event_and_deadline(monkeypatch, stop):
    solver, clock, _, _ = solve_probe(monkeypatch, [visible()])
    event = Event()
    geometry = Mock(return_value=None)
    solver._find_slider_once = geometry
    solver._find_slider = CaptchaSolver._find_slider.__get__(solver)
    summary = solver._page_challenge_summary

    def stop_after_summary():
        value = summary()
        if stop == "cancelled":
            event.set()
        else:
            clock[0] = 10
        return value

    solver._page_challenge_summary = stop_after_summary
    budget = SolveBudget(deadline=10, clock=lambda: clock[0], cancel_event=event)
    assert (
        solver._solve_attempts(
            max_attempts=1, slider_find_max_retries=1, _budget=budget
        )
        is False
    )
    assert solver.last_failure_reason == stop
    geometry.assert_called_once_with()
    solver._reload_page.assert_not_called()
    solver._do_drag.assert_not_called()


def test_failed_summary_is_not_permission_to_confirm_geometry(monkeypatch):
    solver, _, _, _ = solve_probe(monkeypatch, [visible(probeFailed=True)])
    assert solver.solve(max_attempts=1, slider_find_max_retries=1) is False
    assert solver.last_failure_reason == "cdp_unavailable"
    solver._find_slider.assert_called_once_with(max_retries=1, retry_delay=0)
    solver._do_drag.assert_not_called()


def test_true_unsupported_hard_block_keeps_manual_required(monkeypatch):
    solver, _, _, _ = solve_probe(
        monkeypatch,
        [
            {
                "href": TARGET,
                "readyState": "complete",
                "hasSlider": False,
                "hardBlock": True,
            }
        ],
    )
    assert solver.solve(max_attempts=1, slider_find_max_retries=1) is False
    assert solver.last_failure_reason == "manual_required"
    solver._find_slider.assert_called_once_with(max_retries=1, retry_delay=0)
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()


def test_local_mock_keeps_existing_missing_geometry_contract(monkeypatch):
    solver, _, _, _ = solve_probe(monkeypatch, [visible()])
    monkeypatch.setattr(solver, "_is_local_mock_slider_target", lambda: True)
    assert solver.solve(max_attempts=1, slider_find_max_retries=1) is False
    assert solver.last_failure_reason == "max_attempts_exceeded"
    solver._find_slider.assert_called_once_with(max_retries=1, retry_delay=0)
    solver._reload_page.assert_called_once_with()


def test_confirmed_geometry_is_not_accepted_as_verification_success(monkeypatch):
    rejected = {
        "href": TARGET,
        "readyState": "complete",
        "hasSlider": False,
        "explicitFailure": True,
        "retryableFailure": True,
    }
    solver, _, _, _ = solve_probe(
        monkeypatch, [visible(), rejected], sliders=[None, SLIDER]
    )
    solver._wait_for_verification_success.return_value = False
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0) is False
    assert solver.last_failure_reason == "challenge_retry_exhausted"
    solver._do_drag.assert_called_once()
    solver._reset_failed_nc_challenge.assert_not_called()
    solver._reload_page.assert_not_called()


def test_geometry_deferral_retains_existing_safe_missing_slider_diagnostic(monkeypatch):
    solver, _, _, _ = solve_probe(
        monkeypatch,
        [visible(probeFailed=False, hardBlock=True, bodyText="private-body-marker")],
    )
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "slider_not_found"
    assert len(events) == 1 and events[0]["phase"] == "slider_missing"
    assert events[0]["target_ready"] and events[0]["hard_block"]
    assert "private-" not in str(events)
