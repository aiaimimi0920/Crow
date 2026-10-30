"""A reappeared slider must not receive stale retry-widget clicks."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import captcha_nc_retry
from src.captcha_budget import SolveBudget
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_nc_retry_preclick_binding import SEED, probe, ready
from tools.test.test_captcha_nc_retry_uncertain import retry_click_probe
from tools.test.test_captcha_solve_loading_transition import (
    FAILED,
    SLIDER,
    TARGET,
    solve_probe,
)


@pytest.mark.parametrize("target", [TARGET, SEED])
@pytest.mark.parametrize("state", ["interactive", "complete"])
@pytest.mark.parametrize("after_click", [False, True])
def test_reappeared_bound_slider_stops_old_candidate_input(
    monkeypatch, target, state, after_click
):
    recovered = ready(target, readyState=state, hasSlider=True, explicitFailure=False)
    solver = probe(monkeypatch, recovered, target)
    reads = [ready(target, **FAILED)] if after_click else []
    solver._refresh_challenge_summary = Mock(
        side_effect=lambda _: reads.pop(0) if reads else recovered
    )
    assert solver._reset_failed_nc_challenge() is False
    assert solver._click_css_point.call_count == int(after_click)
    assert solver._nc_retry_outcome.call_count == int(after_click)
    assert solver._find_slider.call_count == 0


def test_real_poll_late_slider_never_gets_a_second_stale_retry_click(monkeypatch):
    solver = CaptchaSolver(target_url=TARGET)
    clock, clicks, geometry_at = [0.0], [], []
    monkeypatch.setattr(
        captcha_nc_retry, "time", SimpleNamespace(time=lambda: clock[0])
    )
    monkeypatch.setattr(captcha_nc_retry.random, "uniform", lambda low, high: low)
    solver._wait_interruptibly = lambda seconds: clock.__setitem__(
        0, clock[0] + seconds
    )
    solver._refresh_challenge_summary = lambda _: ready(
        hasSlider=clock[0] >= 3.0, explicitFailure=clock[0] < 3.0
    )
    solver._find_slider = lambda **_: geometry_at.append(clock[0]) or dict(SLIDER)
    retry_click_probe(solver)
    solver._click_css_point.side_effect = lambda *a, **kw: (
        clicks.append(clock[0]) or True
    )

    restored = solver._reset_failed_nc_challenge()
    assert clicks == [0.0]
    assert restored is False
    assert len(geometry_at) == 2
    assert 3.0 < min(geometry_at) < max(geometry_at) < clock[0] < 4.0


@pytest.mark.parametrize("target", [TARGET, SEED])
def test_still_failed_slider_keeps_original_candidate_sequence(monkeypatch, target):
    solver = probe(monkeypatch, ready(target, hasSlider=True, **FAILED), target)
    solver._nc_retry_outcome.side_effect = [
        {"authenticated": False},
        {"slider": SLIDER},
    ]
    assert solver._reset_failed_nc_challenge() is True
    assert solver._click_css_point.call_count == 2


def test_other_call_scene_keeps_original_retry_contract(monkeypatch):
    solver = probe(
        monkeypatch,
        ready(hasSlider=True, explicitFailure=False),
        "https://example.test/slider",
    )
    solver._nc_retry_outcome.return_value = {"slider": SLIDER}
    assert solver._reset_failed_nc_challenge() is True
    solver._click_css_point.assert_called_once()


@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
def test_stop_after_reappeared_summary_still_wins(monkeypatch, reason):
    solver = probe(monkeypatch, ready(hasSlider=True, explicitFailure=False))
    clock = [0.0]
    budget = SolveBudget(deadline=10, clock=lambda: clock[0])

    def stop_after_read(_):
        if reason == "cancelled":
            budget.event.set()
        else:
            clock[0] = 10
        return ready(hasSlider=True, explicitFailure=False)

    solver._refresh_challenge_summary = stop_after_read
    with budget.scope(solver), pytest.raises(captcha_nc_retry.NCRetryTargetUnconfirmed):
        solver._reset_failed_nc_challenge()
    assert solver.last_failure_reason == reason
    solver._click_css_point.assert_not_called()


@pytest.mark.parametrize("verified", [False, True])
def test_solve_revalidates_reappeared_slider_without_another_retry_click(
    monkeypatch, verified
):
    recovered = ready(hasSlider=True, explicitFailure=False)
    solver, _, _, _ = solve_probe(
        monkeypatch,
        [ready(**FAILED), ready(**FAILED), recovered],
        sliders=[SLIDER, SLIDER],
    )
    solver._reset_failed_nc_challenge = (
        CaptchaSolver._reset_failed_nc_challenge.__get__(solver)
    )
    retry_click_probe(solver)
    solver._nc_retry_outcome = Mock(return_value={"authenticated": False})
    solver._wait_for_verification_success.side_effect = [False, verified]

    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is verified
    solver._click_css_point.assert_called_once()
    solver._nc_retry_outcome.assert_called_once_with(timeout_seconds=3.0)
    assert solver._do_drag.call_count == 2
    assert solver._find_slider.call_count == 2
    if verified:
        solver._reload_page.assert_not_called()
    else:
        assert solver.last_failure_reason == "max_attempts_exceeded"
    solver._send_cdp.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None
