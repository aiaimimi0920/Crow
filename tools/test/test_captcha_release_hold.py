"""Verify endpoint hold ordering without a browser or real mouse input."""

import json

import pytest

from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver


class RecordingPointer:
    supports_duration = True

    def __init__(self):
        self.events = []
        self.xy = (0, 0)
        self.down = False

    def position(self):
        return self.xy

    def move(self, x, y, duration=0):
        self.xy = (x, y)
        self.events.append(("move", x, y))

    def left_button(self, *, down):
        self.down = down
        self.events.append(("button", down))

    def wait(self, seconds):
        self.events.append(("wait", seconds, self.down, self.xy))


def make_drag(monkeypatch, backend, variant=0, fraction=0.0):
    pointer = RecordingPointer()
    solver = CaptchaSolver(pointer_backend=pointer)
    monkeypatch.setattr(solver, "_wait_interruptibly", pointer.wait)

    def sample(low, high):
        result = low + (high - low) * fraction
        if (low, high) == (1.5, 2.5):
            pointer.events.append(("sample", low, high, result))
        return result

    monkeypatch.setattr("src.captcha_os_input.random.uniform", sample)
    if backend == "os":
        monkeypatch.setattr(solver, "_enable_process_dpi_awareness", lambda: None)
        monkeypatch.setattr(solver, "_focus_os_window", lambda: True)
        monkeypatch.setattr(
            solver,
            "_map_css_to_screen",
            lambda *args, **kwargs: {
                "x": 100,
                "y": 50,
                "distance": 260,
                "source": "test",
                "located": True,
            },
        )
        drag = lambda: solver._do_drag_os(100, 50, 260, profile_variant_index=variant)
    else:

        def dispatch(_method, params):
            event_type = params["type"]
            if event_type == "mouseMoved":
                pointer.move(params["x"], params["y"])
            else:
                pointer.left_button(down=event_type == "mousePressed")
            return {}

        class Socket:
            def settimeout(self, value):
                pass

            def send(self, raw):
                dispatch("Input.dispatchMouseEvent", json.loads(raw)["params"])

            def close(self):
                pass

        solver.ws = Socket()
        monkeypatch.setattr(solver, "_send_cdp", dispatch)
        drag = lambda: solver._do_drag(100, 50, 260)
    return solver, pointer, drag


@pytest.mark.parametrize("fraction", [0.0, 0.37, 1.0])
@pytest.mark.parametrize(
    "backend,variant", [("os", 0), ("os", 1), ("os", 2), ("cdp", 0)]
)
def test_drag_samples_endpoint_hold_in_range_for_every_attempt(
    monkeypatch, backend, variant, fraction
):
    _solver, pointer, drag = make_drag(monkeypatch, backend, variant, fraction)

    for _ in range(2):
        pointer.events.clear()
        assert drag() == 360

        release_index = pointer.events.index(("button", False))
        move, sample, hold = pointer.events[release_index - 3 : release_index]
        assert move[0] == "move"
        assert move[1] == 360
        assert sample == ("sample", 1.5, 2.5, 1.5 + fraction)
        assert hold == ("wait", 1.5 + fraction, True, move[1:])
        assert not pointer.down


@pytest.mark.parametrize("backend", ["os", "cdp"])
@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
def test_endpoint_hold_can_stop_and_still_releases_button(monkeypatch, backend, reason):
    solver, pointer, drag = make_drag(monkeypatch, backend)
    now = [0.0]

    class StopDuringHold:
        def is_set(self):
            return reason == "cancelled" and now[0] >= 0.3

        def wait(self, seconds):
            now[0] += seconds

    budget = SolveBudget(
        deadline=0.3 if reason == "deadline_exceeded" else 100,
        cancel_event=StopDuringHold(),
        clock=lambda: now[0],
    )

    def wait(seconds):
        pointer.wait(seconds)
        if seconds == 1.5:
            assert pointer.down
            assert pointer.xy[0] == 360
            budget.wait(seconds)

    monkeypatch.setattr(solver, "_wait_interruptibly", wait)
    with pytest.raises(SolveStopped), budget.scope(solver):
        drag()

    assert now[0] == pytest.approx(0.3)
    assert solver.last_failure_reason == reason
    assert pointer.events[-1] == ("button", False)
    assert not pointer.down
    assert not solver.lock.locked()
    assert solver._solve_budget is None
