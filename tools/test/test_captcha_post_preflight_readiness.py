"""A challenge may start mounting only after the initial preflight read."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import captcha_nc_retry
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_login_recovery_readiness import TARGET, recovery_solver
from tools.test.test_captcha_solve_loading_transition import SLIDER, solve_probe


@pytest.mark.parametrize("start_loading", [False, True])
def test_interactive_challenge_after_preflight_reuses_bounded_readiness_wait(
    monkeypatch, start_loading
):
    solver, clock = recovery_solver(monkeypatch)
    initial = {"href": TARGET, "readyState": "interactive", "hardBlock": True}
    solver._page_challenge_summary = lambda **_kwargs: {
        **initial,
        "readyState": "complete" if clock[0] >= 12 else "interactive",
        "hasSlider": clock[0] >= 12,
    }
    geometry = {"x": 100, "y": 100, "width": 42, "height": 30}
    solver._find_slider = Mock(return_value=geometry)
    slider, summary = solver._confirm_missing_slider(
        {**initial, "readyState": "loading"} if start_loading else initial
    )
    assert slider == geometry
    assert summary["hasSlider"] is True
    assert clock[0] == 15 + (0.25 if start_loading else 0)
    solver._find_slider.assert_called_once_with(max_retries=1, retry_delay=0)
    solver._recover_authenticated_list_page.assert_not_called()


@pytest.mark.parametrize("start_loading", [False, True])
def test_single_attempt_solve_waits_for_post_preflight_slider_without_reloading(
    monkeypatch, start_loading
):
    solver, clock, _, _ = solve_probe(monkeypatch, [{}], sliders=[None, SLIDER])
    monkeypatch.setattr(
        captcha_nc_retry,
        "time",
        SimpleNamespace(time=lambda: clock[0], monotonic=lambda: clock[0]),
    )
    solver._poll_until_authenticated = CaptchaSolver._poll_until_authenticated.__get__(
        solver
    )
    solver._focus_os_window = Mock()
    solver._login_wait_seconds = Mock(return_value=30)
    solver._page_challenge_summary = lambda **_kwargs: {
        "href": solver.target_url,
        "readyState": (
            "complete"
            if clock[0] >= 12
            else "loading"
            if start_loading and clock[0] == 0
            else "interactive"
        ),
        "hardBlock": True,
        "hasSlider": clock[0] >= 12,
    }
    assert solver.solve(max_attempts=1, slider_find_max_retries=1) is True
    assert solver._find_slider.call_count == 2
    solver._do_drag.assert_called_once()
    solver._recover_authenticated_list_page.assert_not_called()
    solver._reset_failed_nc_challenge.assert_not_called()
    solver._reload_page.assert_not_called()
    solver._send_cdp.assert_not_called()


@pytest.mark.parametrize(
    "state", ["complete", "probeFailed", "authenticatedPage", "loginRequired"]
)
def test_post_preflight_wait_does_not_replace_terminal_or_login_policy(
    monkeypatch, state
):
    solver, _ = recovery_solver(monkeypatch)
    solver._poll_until_authenticated = Mock()
    summary = {"href": TARGET, "readyState": "interactive"}
    if state == "complete":
        summary["readyState"] = "complete"
    else:
        summary[state] = True
    solver._find_slider = Mock()
    assert solver._confirm_missing_slider(summary) == (None, summary)
    solver._poll_until_authenticated.assert_not_called()
    solver._find_slider.assert_not_called()
