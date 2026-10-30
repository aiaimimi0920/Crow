"""A missing CDP input ACK is not permission to reload or destroy its page."""

import json
from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveBudget
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_solve_loading_transition import (
    AUTHENTICATED,
    SLIDER,
    solve_probe,
)


def input_probe(monkeypatch, phase, *, owned=False, stop=None):
    solver, clock, reads, waits = solve_probe(
        monkeypatch, [AUTHENTICATED], sliders=[SLIDER] * 3
    )
    budget = SolveBudget(deadline=100, clock=lambda: clock[0])
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_: budget)
    solver.ws = socket = Mock()
    solver._cdp_mouse_down = False
    solver._do_drag = Mock(wraps=CaptchaSolver._do_drag.__get__(solver))
    solver._generate_bezier_path = Mock(return_value=[(100, 50, 0.5)])
    solver._close_owned_target_tabs = CaptchaSolver._close_owned_target_tabs.__get__(
        solver
    )
    solver._close_cdp_target = Mock(return_value=True)
    if owned:
        solver._opened_target_ids.update({"owned", "owned-probe"})
        solver.target_id = "owned"
    events = []

    def send(method, params):
        assert method == "Input.dispatchMouseEvent"
        event, buttons = params["type"], params["buttons"]
        events.append((event, buttons))
        failed = {
            "approach": event == "mouseMoved" and buttons == 0,
            "press": event == "mousePressed",
            "move": event == "mouseMoved" and buttons == 1,
            "release": event == "mouseReleased",
        }[phase]
        if failed:
            if stop == "cancelled":
                budget.event.set()
            elif stop == "deadline_exceeded":
                clock[0] = budget.deadline
            return None
        return {}

    solver._send_cdp = Mock(side_effect=send)
    return solver, budget, clock, reads, waits, socket, events


@pytest.mark.parametrize("phase", ["approach", "press", "move", "release"])
@pytest.mark.parametrize("attempts", [1, 3])
@pytest.mark.parametrize("owned", [False, True])
def test_uncertain_cdp_input_preserves_page_without_reload_or_another_gesture(
    monkeypatch, phase, attempts, owned
):
    solver, budget, _, reads, _, socket, events = input_probe(
        monkeypatch, phase, owned=owned
    )

    assert solver.solve(max_attempts=attempts) is False

    assert solver.last_failure_reason == "cdp_unavailable"
    assert budget.deadline == 100 and budget.reason is None
    assert solver._opened_target_ids == ({"owned", "owned-probe"} if owned else set())
    assert solver.ws is None and solver._cdp_mouse_down is False
    assert socket.close.call_count == 1
    solver._find_slider.assert_called_once()
    solver._do_drag.assert_called_once()
    solver._close_cdp_target.assert_not_called()
    for action in (
        solver._reload_page,
        solver._wait_for_verification_success,
        solver._reset_failed_nc_challenge,
        solver._recover_authenticated_list_page,
    ):
        action.assert_not_called()
    # The failed transport is not trusted enough to claim authenticated success.
    assert reads == [0]
    assert (
        events[-1]
        == {
            "approach": ("mouseMoved", 0),
            "press": ("mousePressed", 1),
            "move": ("mouseMoved", 1),
            "release": ("mouseReleased", 0),
        }[phase]
    )
    releases = [json.loads(call.args[0]) for call in socket.send.call_args_list]
    assert len(releases) == (0 if phase == "approach" else 1)
    assert all(event["params"]["type"] == "mouseReleased" for event in releases)
    assert not solver.lock.locked() and solver._solve_budget is None


@pytest.mark.parametrize("phase", ["press", "release"])
@pytest.mark.parametrize("stop", ["cancelled", "deadline_exceeded"])
def test_input_uncertainty_keeps_cancellation_and_deadline_priority(
    monkeypatch, phase, stop
):
    solver, budget, _, _, _, _, _ = input_probe(
        monkeypatch, phase, owned=True, stop=stop
    )
    assert solver.solve(max_attempts=3) is False
    assert solver.last_failure_reason == budget.reason == stop
    assert budget.deadline == 100
    assert solver._opened_target_ids == {"owned", "owned-probe"}
    solver._reload_page.assert_not_called()
    solver._close_cdp_target.assert_not_called()
    solver._do_drag.assert_called_once()
    assert solver.ws is None and not solver._cdp_mouse_down
    assert not solver.lock.locked() and solver._solve_budget is None


@pytest.mark.parametrize("owned", [False, True])
def test_uncertain_native_input_also_retains_owned_pages(monkeypatch, owned):
    solver, _, _, reads, _, _, _ = input_probe(monkeypatch, "release", owned=owned)
    solver._os_mouse_enabled.return_value = True

    def uncertain_native(*_args, **_kwargs):
        solver.last_failure_reason = "os_button_state_unverified"

    solver._do_drag_os = Mock(side_effect=uncertain_native)
    assert solver.solve(max_attempts=3) is False
    assert solver.last_failure_reason == "execution_unavailable"
    assert solver._opened_target_ids == ({"owned", "owned-probe"} if owned else set())
    solver._close_cdp_target.assert_not_called()
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()
    assert reads == [0]


def test_acknowledged_success_keeps_normal_owned_page_cleanup(monkeypatch):
    solver, _, _, _, _, _, _ = input_probe(monkeypatch, "release", owned=True)
    solver._send_cdp.side_effect = None
    solver._send_cdp.return_value = {}
    assert solver.solve(max_attempts=1) is True
    assert solver.last_failure_reason is None
    assert solver._opened_target_ids == set()
    assert solver._close_cdp_target.call_count == 2
    solver._do_drag.assert_called_once()
    solver._reload_page.assert_not_called()


def test_other_incomplete_drag_keeps_existing_retry_and_cleanup(monkeypatch):
    solver, _, _, _, _, _, _ = input_probe(monkeypatch, "release", owned=True)

    def incomplete(*_args):
        solver.last_failure_reason = "slider_not_found"

    solver._do_drag.side_effect = incomplete
    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "max_attempts_exceeded"
    assert solver._opened_target_ids == set()
    assert solver._close_cdp_target.call_count == 2
    solver._reload_page.assert_called_once()
