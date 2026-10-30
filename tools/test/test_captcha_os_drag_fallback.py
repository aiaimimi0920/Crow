"""An ambiguous physical gesture must not authorize a second CDP gesture."""

from unittest.mock import Mock

import pytest

from tools.test.test_captcha_solve_loading_transition import SLIDER, solve_probe


class FailingPointer:
    supports_duration = True

    def __init__(self, failure):
        self.failure = failure
        self.xy = (0, 0)
        self.buttons = []
        self.down = False
        self.failed = False

    def position(self):
        return self.xy

    def move(self, x, y, duration=0):
        self.xy = (x, y)
        if (self.failure == "approach" or self.down) and self.failure in {
            "approach",
            "move",
        }:
            raise RuntimeError("injected physical movement failure")

    def left_button(self, *, down):
        self.buttons.append(down)
        self.down = down
        if not self.failed and self.failure == ("press" if down else "release"):
            self.failed = True
            raise RuntimeError("injected physical button failure")


def physical_solve(monkeypatch, failure):
    solver, _, _, _ = solve_probe(monkeypatch, [{}], sliders=[SLIDER])
    pointer = FailingPointer(failure)
    solver._pointer_backend_override = pointer
    solver._os_mouse_enabled.return_value = True
    solver._enable_process_dpi_awareness = Mock()
    solver._focus_os_window = Mock(return_value=True)
    solver._map_css_to_screen = Mock(
        return_value={
            "x": 100,
            "y": 50,
            "distance": 250,
            "source": "fake",
            "located": True,
        }
    )
    solver._ensure_os_left_button_released = Mock(
        side_effect=[True, RuntimeError("injected post-release failure")]
        if failure == "after_release"
        else None,
        return_value=True,
    )
    solver._os_drag_warmup_points = Mock(return_value=[])
    solver._os_drag_track = Mock(return_value=([1], [0]))
    solver._os_drag_y_track = Mock(return_value=[])
    solver._os_drag_release_plan = Mock(return_value=(350, [350], 350))
    return solver, pointer


@pytest.mark.parametrize(
    "failure", ["approach", "press", "move", "release", "after_release"]
)
def test_real_os_failure_never_falls_back_to_another_gesture(monkeypatch, failure):
    solver, pointer = physical_solve(monkeypatch, failure)
    result = solver.solve(max_attempts=1, nc_retry_replay_limit=2)
    solver._do_drag.assert_not_called()
    assert result is False
    assert not pointer.down
    if failure != "approach":
        assert pointer.buttons[0] is True and pointer.buttons[-1] is False
    solver._wait_for_verification_success.assert_not_called()
    solver._reload_page.assert_not_called()
    assert solver.last_failure_reason == "execution_unavailable"
    solver._reset_failed_nc_challenge.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


def test_os_exception_defers_remaining_attempts_without_reloading(
    monkeypatch,
):
    solver, pointer = physical_solve(monkeypatch, "move")
    solver._find_slider.side_effect = [SLIDER, {**SLIDER, "x": 80}]
    solver._do_drag_os = Mock(wraps=solver._do_drag_os)
    assert solver.solve(max_attempts=2, nc_retry_replay_limit=2) is False
    assert solver.last_failure_reason == "execution_unavailable"
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()
    assert solver._find_slider.call_count == solver._do_drag_os.call_count == 1
    assert not pointer.down
    solver._wait_for_verification_success.assert_not_called()


def test_successful_physical_drag_keeps_existing_verification(monkeypatch):
    solver, pointer = physical_solve(monkeypatch, None)
    assert solver.solve(max_attempts=1) is True
    assert pointer.buttons == [True, False]
    solver._do_drag.assert_not_called()
    solver._wait_for_verification_success.assert_called_once()
    solver._reload_page.assert_not_called()


@pytest.mark.parametrize("reason", [None, "uinput_unavailable"])
def test_unavailable_backend_before_input_retains_existing_cdp_fallback(
    monkeypatch, reason
):
    solver, _, _, _ = solve_probe(monkeypatch, [{}], sliders=[SLIDER])
    solver._os_mouse_enabled.return_value = True

    def unavailable(*_args, **_kwargs):
        solver.last_failure_reason = reason

    solver._do_drag_os = Mock(side_effect=unavailable)
    assert solver.solve(max_attempts=1) is True
    solver._do_drag_os.assert_called_once()
    solver._do_drag.assert_called_once()
    solver._wait_for_verification_success.assert_called_once()


@pytest.mark.parametrize(
    "reason",
    [
        "window_focus_failed",
        "screen_mapping_target_changed",
        "os_cursor_position_unverified",
        "os_button_state_unverified",
    ],
)
def test_existing_unsafe_target_failures_still_block_cdp(monkeypatch, reason):
    solver, _, _, _ = solve_probe(monkeypatch, [{}], sliders=[SLIDER])
    solver._os_mouse_enabled.return_value = True

    def unavailable(*_args, **_kwargs):
        solver.last_failure_reason = reason

    solver._do_drag_os = Mock(side_effect=unavailable)
    assert solver.solve(max_attempts=1) is False
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()
    assert solver.last_failure_reason == "execution_unavailable"


@pytest.mark.parametrize("local_mock", [False, True])
def test_other_input_paths_are_unchanged(monkeypatch, local_mock):
    solver, _, _, _ = solve_probe(monkeypatch, [{}], sliders=[SLIDER])
    solver._is_local_mock_slider_target = Mock(return_value=local_mock)
    solver._do_drag_os = Mock()
    solver._do_drag_local_mock = Mock(return_value=1)
    assert solver.solve(max_attempts=1) is True
    solver._do_drag_os.assert_not_called()
    assert solver._do_drag.call_count == int(not local_mock)
    assert solver._do_drag_local_mock.call_count == int(local_mock)
