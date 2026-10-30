"""Terminal geometry is not permission for another gesture or proof of success."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import captcha_slider_geometry as geometry
from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_os_target import OSPointerTarget
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_release_hold import make_drag
from tools.test.test_captcha_solve_loading_transition import TARGET, solve_probe

SEED = "https://sf.taobao.com/list/1.htm?page=2&location_code=31"
ENDPOINT = {
    "x": 823.5,
    "y": 40,
    "width": 42,
    "height": 30,
    "track_rect": {
        "left": 565.5,
        "width": 300,
        "offsetWidth": 300,
        "handleOffsetWidth": 42,
        "handleOffsetLeft": 258,
    },
}


def endpoint_solver(monkeypatch, target=TARGET, os_input=False):
    visible = {"href": target, "readyState": "complete", "hasSlider": True}
    solver, clock, reads, waits = solve_probe(
        monkeypatch, [visible], sliders=[ENDPOINT.copy() for _ in range(20)]
    )
    solver.target_url = target
    solver._os_mouse_enabled.return_value = os_input
    solver._do_drag_os = Mock(return_value=1)
    solver._opened_target_ids.add("retained")
    return solver, clock, reads, waits


@pytest.mark.parametrize("target", [TARGET, SEED])
@pytest.mark.parametrize("os_input", [False, True])
def test_endpoint_without_success_preserves_page_without_reinput(
    monkeypatch, target, os_input, caplog
):
    solver, _, _, _ = endpoint_solver(monkeypatch, target, os_input)
    solver._wait_for_verification_success.return_value = False
    with caplog.at_level("INFO"):
        assert solver.solve(max_attempts=5, nc_retry_replay_limit=2) is False
    assert solver.last_failure_reason == "slider_endpoint_unconfirmed"
    solver._wait_for_verification_success.assert_called_once_with()
    solver._do_drag.assert_not_called()
    solver._do_drag_os.assert_not_called()
    solver._reload_page.assert_not_called()
    solver._reset_failed_nc_challenge.assert_not_called()
    solver._close_owned_target_tabs.assert_not_called()
    assert solver._opened_target_ids == {"retained"}
    assert solver._find_slider.call_count == 1
    assert "Verified: Captcha solved" not in caplog.text
    assert solver._solve_budget is None and not solver.lock.locked()


def test_endpoint_success_still_requires_existing_verification(monkeypatch, caplog):
    solver, _, _, _ = endpoint_solver(monkeypatch)
    with caplog.at_level("INFO"):
        assert solver.solve(max_attempts=1) is True
    solver._wait_for_verification_success.assert_called_once_with()
    solver._do_drag.assert_not_called()
    solver._do_drag_os.assert_not_called()
    assert solver.last_failure_reason is None
    assert "Verified: Captcha solved" not in caplog.text


@pytest.mark.parametrize("state", ["visible", "rejected", "probe_failed", "foreign"])
def test_endpoint_does_not_bypass_live_verification_or_retry_errors(monkeypatch, state):
    solver, _, _, _ = endpoint_solver(monkeypatch)
    solver._wait_for_verification_success = (
        CaptchaSolver._wait_for_verification_success.__get__(solver)
    )
    solver._verify_success = Mock(return_value=False)
    summary = {"href": TARGET, "readyState": "complete", "hasSlider": True}
    if state == "rejected":
        summary.update(explicitFailure=True, retryableFailure=True)
    elif state == "probe_failed":
        summary.update(probeFailed=True)
    elif state == "foreign":
        summary["href"] = TARGET.replace("123", "456")
    solver._page_challenge_summary = Mock(return_value=summary)
    assert solver.solve(max_attempts=5) is False
    assert solver.last_failure_reason == "slider_endpoint_unconfirmed"
    solver._do_drag.assert_not_called()
    solver._reset_failed_nc_challenge.assert_not_called()
    solver._reload_page.assert_not_called()
    assert 1 <= solver._verify_success.call_count <= 6


@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
def test_endpoint_verification_never_extends_solve_budget(monkeypatch, reason):
    solver, clock, _, _ = endpoint_solver(monkeypatch)
    solver._wait_for_verification_success = (
        CaptchaSolver._wait_for_verification_success.__get__(solver)
    )
    solver._verify_success = Mock(return_value=False)
    event = SimpleNamespace(
        is_set=lambda: reason == "cancelled" and clock[0] >= 3,
        wait=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    budget = SolveBudget(
        deadline=3 if reason == "deadline_exceeded" else 100,
        clock=lambda: clock[0],
        cancel_event=event,
    )
    solver._wait_interruptibly = CaptchaSolver._wait_interruptibly.__get__(solver)
    with pytest.raises(SolveStopped, match=reason):
        solver._solve_attempts(max_attempts=5, _budget=budget)
    assert solver.last_failure_reason == reason
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()
    # Preserve the existing SolveBudget cancellation cleanup, not a new exemption.
    solver._close_owned_target_tabs.assert_called_once_with()
    assert solver._solve_budget is None and not solver.lock.locked()


@pytest.mark.parametrize("bound", [False, True])
def test_fresh_native_probe_at_endpoint_stops_before_mapping_or_pointer(
    monkeypatch, bound
):
    solver, pointer, _ = make_drag(monkeypatch, "os")
    probe = SimpleNamespace(
        enabled=True,
        rect=ENDPOINT,
        point=(844.5, 55),
        scale=1,
        geometry_bound=bound,
        track_rect=ENDPOINT["track_rect"],
        open=lambda: True,
        verify=Mock(),
    )
    solver._get_track_width = Mock(return_value=300)
    solver._get_track_rect = Mock(return_value=ENDPOINT["track_rect"])
    solver._map_css_to_screen = Mock()
    with pytest.raises(geometry.SliderEndpointReached):
        solver._do_drag_os_target(592, 55, 256, {"selector": "#handle"}, 0, probe)
    solver._map_css_to_screen.assert_not_called()
    probe.verify.assert_not_called()
    assert not [e for e in pointer.events if e[0] in {"button", "move"}]
    assert not pointer.down


@pytest.mark.parametrize("confirmed", [False, True])
def test_fresh_native_endpoint_is_not_caught_as_input_failure_or_cdp_fallback(
    monkeypatch,
    confirmed,
):
    from src import captcha_os_input

    solver, _, _, _ = endpoint_solver(monkeypatch, os_input=True)
    solver._find_slider.side_effect = None
    solver._find_slider.return_value = {
        **ENDPOINT,
        "x": 567.5,
        "track_rect": {**ENDPOINT["track_rect"], "handleOffsetLeft": 2},
    }
    # Initial geometry is nonterminal; only the post-focus probe sees the endpoint.
    pointer_solver, pointer, _ = make_drag(monkeypatch, "os")
    solver._pointer_backend_override = pointer
    solver._enable_process_dpi_awareness = pointer_solver._enable_process_dpi_awareness
    solver._focus_os_window = pointer_solver._focus_os_window
    probe = SimpleNamespace(
        solver=solver,
        enabled=True,
        rect=ENDPOINT,
        point=(844.5, 55),
        scale=1,
        geometry_bound=True,
        track_rect=ENDPOINT["track_rect"],
        open=lambda: True,
        close=Mock(),
    )
    probe.run_drag = OSPointerTarget.run_drag.__get__(probe)
    monkeypatch.setattr(captcha_os_input, "OSPointerTarget", lambda *_: probe)
    solver._do_drag_os = CaptchaSolver._do_drag_os.__get__(solver)
    solver._wait_for_verification_success.return_value = confirmed
    assert solver.solve(max_attempts=1) is confirmed
    assert solver.last_failure_reason == (
        None if confirmed else "slider_endpoint_unconfirmed"
    )
    probe.close.assert_called_once_with()
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()
    assert not pointer.down
