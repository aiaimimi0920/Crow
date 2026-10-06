"""Lock the existing production drag phases without browser or pointer input."""

import pytest

from src.captcha_budget import SolveBudget, SolveStopped
from tools.test.test_captcha_release_hold import make_drag

BACKENDS = [("os", 0), ("os", 1), ("os", 2), ("cdp", 0)]


@pytest.mark.parametrize("backend,variant", BACKENDS)
@pytest.mark.parametrize("fraction", [0.0, 0.37, 1.0])
def test_drag_pauses_on_handle_before_press_and_before_first_move(
    monkeypatch, backend, variant, fraction
):
    solver, pointer, drag = make_drag(monkeypatch, backend, variant, fraction)
    assert drag() == 360
    press_index = pointer.events.index(("button", True))
    approach, before_press = pointer.events[press_index - 2 : press_index]
    after_press = pointer.events[press_index + 1]

    assert approach == ("move", 100, 50)
    assert before_press[0] == after_press[0] == "wait"
    assert before_press[2:] == (False, (100, 50))
    assert after_press[2:] == (True, (100, 50))
    ranges = (
        [solver._os_drag_profile(variant)["press_hold"]] * 2
        if backend == "os"
        else [(0.35, 0.75), (0.18, 0.38)]
    )
    for event, (low, high) in zip((before_press, after_press), ranges, strict=True):
        assert 0 < low <= event[1] <= high
        assert event[1] == pytest.approx(low + (high - low) * fraction)


@pytest.mark.parametrize("backend,variant", BACKENDS)
def test_drag_applies_small_xy_tremor_while_pressed_and_restores_endpoint(
    monkeypatch, backend, variant
):
    solver, pointer, drag = make_drag(monkeypatch, backend, variant, fraction=0.5)
    monkeypatch.setattr("src.captcha_os_input.random.random", lambda: 1.0)
    # Alternate deterministic half-sigma offsets to prove both directions reach
    # the pointer backend, rather than only asserting that a profile has fields.
    offsets = iter([0.5, 0.5, -0.5, -0.5, 0.5, 0.5])
    monkeypatch.setattr(
        "src.captcha_os_input.random.gauss",
        lambda mean, sigma: mean + sigma * next(offsets, 0.0),
    )
    fractions = [0.25, 0.5, 0.75]
    if backend == "os":
        monkeypatch.setattr(solver, "_os_drag_warmup_points", lambda *args: [])
        monkeypatch.setattr(
            solver, "_os_drag_track", lambda *args: (fractions, [0.01] * 3)
        )
        profile = solver._os_drag_profile(variant)
        sigma_x, sigma_y = profile["tremor_x"], profile["tremor_y"]
    else:
        monkeypatch.setattr(
            solver,
            "_generate_bezier_path",
            lambda *args: [(100 + 260 * f, 50, f) for f in fractions],
        )
        sigma_x, sigma_y = 0.7, 1.1

    assert drag() == 360
    press_index = pointer.events.index(("button", True))
    release_index = pointer.events.index(("button", False))
    moves = [e for e in pointer.events[press_index:release_index] if e[0] == "move"]
    for event, fraction, sign in zip(moves[:3], fractions, [1, -1, 1], strict=True):
        assert event[1] == pytest.approx(100 + 260 * fraction + sign * sigma_x / 2)
        assert event[2] == pytest.approx(50 + sign * sigma_y / 2)
        assert 0 < sigma_x <= 1.0 and 0 < sigma_y <= 1.1
    assert moves[-1][1] == 360
    assert pointer.events[release_index - 1][0] == "wait"
    assert not pointer.down


@pytest.mark.parametrize("backend,variant", BACKENDS)
@pytest.mark.parametrize("after_press", [False, True])
@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
def test_start_pause_remains_interruptible_without_dragging_or_stuck_button(
    monkeypatch, backend, variant, after_press, reason
):
    solver, pointer, drag = make_drag(monkeypatch, backend, variant, fraction=0.5)
    now = [0.0]

    class Cancellation:
        def is_set(self):
            return reason == "cancelled" and now[0] >= 0.03

        def wait(self, seconds):
            now[0] += seconds

    budget = SolveBudget(
        deadline=0.03 if reason == "deadline_exceeded" else 100,
        cancel_event=Cancellation(),
        clock=lambda: now[0],
    )

    def wait(seconds):
        pointer.wait(seconds)
        if pointer.xy == (100, 50) and pointer.down == after_press:
            budget.wait(seconds)

    monkeypatch.setattr(solver, "_wait_interruptibly", wait)
    with pytest.raises(SolveStopped), budget.scope(solver):
        drag()
    assert solver.last_failure_reason == reason
    assert pointer.xy == (100, 50)
    assert not pointer.down
    assert not solver.lock.locked()
    assert solver._solve_budget is None
    assert (("button", True) in pointer.events) == after_press
    if after_press:
        assert pointer.events[-1] == ("button", False)
