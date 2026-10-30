"""A lost retry-click ACK cannot authorize another click or destroy recovery state."""

import json
from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveBudget
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_solve_loading_transition import FAILED, SLIDER, solve_probe


def click_probe(monkeypatch, phase, entry, *, stop=None, owned=True):
    bound_failure = {
        **FAILED,
        "href": "https://sf-item.taobao.com/sf_item/123.htm",
        "readyState": "complete",
    }
    solver, clock, reads, _ = solve_probe(
        monkeypatch, [bound_failure], sliders=[SLIDER]
    )
    budget = SolveBudget(deadline=100, clock=lambda: clock[0])
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_: budget)
    solver.ws = socket = Mock()
    solver._cdp_mouse_down = False
    solver._reset_failed_nc_challenge = (
        CaptchaSolver._reset_failed_nc_challenge.__get__(solver)
    )
    solver._nc_retry_targets = Mock(
        return_value={"widget": {"x": 10, "y": 20, "width": 280, "height": 40}}
    )
    solver._nc_retry_outcome = Mock(return_value={"slider": SLIDER})
    solver._wait_for_verification_success.return_value = False
    solver._close_owned_target_tabs = CaptchaSolver._close_owned_target_tabs.__get__(
        solver
    )
    solver._close_cdp_target = Mock(return_value=True)
    if owned:
        solver._opened_target_ids.update({"owned", "owned-probe"})
        solver.target_id = "owned"
    if entry == "preflight":
        solver._preflight_current_challenge = (
            CaptchaSolver._preflight_current_challenge.__get__(solver)
        )
    elif entry == "missing_slider":
        solver._find_slider.side_effect = None
        solver._find_slider.return_value = None
    events = []

    def send(method, params):
        assert method == "Input.dispatchMouseEvent"
        event = params["type"]
        events.append(event)
        if event == phase and events.count(phase) == 1:
            if stop == "cancelled":
                budget.event.set()
            elif stop == "deadline_exceeded":
                clock[0] = budget.deadline
            return None
        return {}

    solver._send_cdp = Mock(side_effect=send)
    return solver, budget, reads, socket, events


@pytest.mark.parametrize("phase", ["mousePressed", "mouseReleased"])
@pytest.mark.parametrize("entry", ["preflight", "missing_slider", "after_drag"])
@pytest.mark.parametrize("owned", [False, True])
def test_lost_retry_ack_stops_stale_clicks_and_preserves_recovery_page(
    monkeypatch, phase, entry, owned
):
    solver, budget, reads, socket, events = click_probe(
        monkeypatch, phase, entry, owned=owned
    )

    assert solver.solve(max_attempts=3, nc_retry_replay_limit=1) is False

    assert solver.last_failure_reason == "cdp_unavailable"
    assert budget.reason is None and budget.deadline == 100
    assert events == (
        ["mousePressed"]
        if phase == "mousePressed"
        else ["mousePressed", "mouseReleased"]
    )
    solver._nc_retry_outcome.assert_not_called()
    solver._reload_page.assert_not_called()
    solver._recover_authenticated_list_page.assert_not_called()
    solver._poll_until_authenticated.assert_not_called()
    solver._close_cdp_target.assert_not_called()
    assert solver._do_drag.call_count == int(entry == "after_drag")
    assert reads == [2]
    assert solver._opened_target_ids == ({"owned", "owned-probe"} if owned else set())
    assert solver.ws is None and not solver._cdp_mouse_down
    assert socket.close.call_count == 1
    releases = [json.loads(call.args[0]) for call in socket.send.call_args_list]
    assert len(releases) == 1
    assert releases[0]["params"]["type"] == "mouseReleased"
    assert not solver.lock.locked() and solver._solve_budget is None


@pytest.mark.parametrize("phase", ["mousePressed", "mouseReleased"])
@pytest.mark.parametrize("stop", ["cancelled", "deadline_exceeded"])
def test_retry_ack_failure_preserves_stop_reason_and_budget(monkeypatch, phase, stop):
    solver, budget, _, _, events = click_probe(
        monkeypatch, phase, "after_drag", stop=stop
    )
    assert solver.solve(max_attempts=3, nc_retry_replay_limit=1) is False
    assert solver.last_failure_reason == budget.reason == stop
    assert budget.deadline == 100
    assert events.count("mousePressed") == 1
    assert solver._opened_target_ids == {"owned", "owned-probe"}
    solver._nc_retry_outcome.assert_not_called()
    solver._close_cdp_target.assert_not_called()
    solver._reload_page.assert_not_called()
    assert solver.ws is None and not solver._cdp_mouse_down
    assert not solver.lock.locked() and solver._solve_budget is None


def test_acknowledged_retry_click_keeps_normal_recovery(monkeypatch):
    solver = CaptchaSolver()
    solver._os_mouse_enabled = Mock(return_value=False)
    solver._send_cdp = Mock(return_value={})
    assert solver._click_css_point(100, 50) is True
    assert [call.args[1]["type"] for call in solver._send_cdp.call_args_list] == [
        "mousePressed",
        "mouseReleased",
    ]
    assert solver.last_failure_reason is None and not solver._cdp_mouse_down
