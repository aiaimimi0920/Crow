"""Idle motion cannot overlap a task or fight recent operator input."""

import random

import pytest

from tools import pc2_solver_idle_pointer as idle

SAFE = {"running": False, "paused": False, "manual_required": False}


class Backend:
    def __init__(self, clock):
        self.clock = clock
        self.last_input = -100
        self.position = (400, 300)
        self.points = []
        self.closed = False
        self.override = None

    def snapshot(self):
        state = {
            "window": 7,
            "position": self.position,
            "buttons": 0,
            "idle_seconds": self.clock() - self.last_input,
            "bounds": (100, 150, 800, 650),
        }
        return self.override(state) if self.override else state

    def move(self, x, y):
        self.position = (round(x), round(y))
        self.points.append(self.position)
        self.last_input = self.clock()

    def close(self):
        self.closed = True


def setup_idle(monkeypatch):
    now = [0.0]
    backend = Backend(lambda: now[0])
    monkeypatch.setattr(idle, "idle_mouse_enabled", lambda: True)
    controller = idle.IdlePointer(
        "http://127.0.0.1:9223",
        backend_factory=lambda _port: backend,
        clock=lambda: now[0],
        sleep=lambda delay: now.__setitem__(0, now[0] + delay),
        rng=random.Random(41),
    )
    now[0] = 16
    return controller, backend, now


@pytest.mark.parametrize(
    "status",
    [
        {},
        {"error": "offline"},
        {**SAFE, "running": True},
        {**SAFE, "paused": True},
        {**SAFE, "manual_required": True},
        {**SAFE, "force_reset_required": True},
        {**SAFE, "scopes": {"detail": {**SAFE, "running": True}}},
    ],
)
def test_no_idle_input_when_any_work_or_manual_action_is_pending(monkeypatch, status):
    controller, backend, _now = setup_idle(monkeypatch)
    assert controller.tick(status, lambda: SAFE) is None
    assert backend.points == []


@pytest.mark.parametrize("mode", ["pointer", "keyboard", "button", "window", "outside"])
def test_recent_operator_activity_or_wrong_window_blocks_idle_motion(monkeypatch, mode):
    controller, backend, _now = setup_idle(monkeypatch)
    if mode == "pointer":
        controller.expected = (200, 200)
    if mode == "keyboard":
        backend.last_input = 15
    if mode == "button":
        backend.override = lambda state: {**state, "buttons": 256}
    if mode == "window":
        backend.override = lambda _state: None
    if mode == "outside":
        backend.position = (0, 0)
    assert controller.tick(SAFE, lambda: SAFE) is None
    assert backend.points == []
    assert backend.closed


def test_idle_curve_is_bounded_and_has_variable_intervals(monkeypatch):
    controller, backend, now = setup_idle(monkeypatch)
    intervals = []
    for _ in range(4):
        result = controller.tick(SAFE, lambda: SAFE)
        assert result["kind"] == "idle_pointer_move"
        assert 8 <= result["points"] <= 14
        assert 0.35 <= result["duration"] <= 0.65
        assert 5 <= result["next_in"] <= 18
        intervals.append(result["next_in"])
        now[0] = controller.next_at + 0.01
    assert len(set(intervals)) > 1
    assert all(100 < x < 800 and 150 < y < 650 for x, y in backend.points)
    assert backend.closed


def test_task_appearing_during_idle_curve_interrupts_it(monkeypatch):
    controller, backend, _now = setup_idle(monkeypatch)
    statuses = iter([SAFE, {**SAFE, "running": True}])
    result = controller.tick(SAFE, lambda: next(statuses))
    assert result["kind"] == "idle_pointer_interrupted"
    assert 0 < len(backend.points) < 8


def test_manual_pointer_movement_interrupts_curve_without_restore(monkeypatch):
    controller, backend, _now = setup_idle(monkeypatch)

    def interrupt(state):
        return {**state, "position": (600, 400)} if backend.points else state

    backend.override = interrupt
    result = controller.tick(SAFE, lambda: SAFE)
    assert result == {"kind": "idle_pointer_interrupted", "points": 1}
    assert len(backend.points) == 1


def test_idle_requires_host_display_and_existing_os_input_opt_in(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        idle, "os", SimpleNamespace(name="posix", environ={"DISPLAY": ":1"})
    )
    values = {
        "CROW_BROWSER_DISPLAY_MODE": "host",
        "CROW_BROWSER_HOST_DISPLAY": ":1",
        "CROW_SOLVER_OS_MOUSE": "1",
    }
    monkeypatch.setattr(
        idle, "getenv", lambda key, default="": values.get(key, default)
    )
    assert idle.idle_mouse_enabled()
    values["CROW_SOLVER_IDLE_MOUSE"] = "0"
    assert not idle.idle_mouse_enabled()
    values.pop("CROW_SOLVER_IDLE_MOUSE")
    values["CROW_SOLVER_OS_MOUSE"] = "0"
    assert not idle.idle_mouse_enabled()
    values["CROW_SOLVER_OS_MOUSE"] = "1"
    values["CROW_BROWSER_DISPLAY_MODE"] = "xvfb"
    assert not idle.idle_mouse_enabled()


def test_real_api_scopes_inherit_aggregate_running_flag(monkeypatch):
    controller, backend, _now = setup_idle(monkeypatch)
    status = {
        **SAFE,
        "scopes": {"seed": {"paused": False}, "detail": {"paused": False}},
    }
    assert controller.tick(status, lambda: status)["kind"] == "idle_pointer_move"
    assert backend.points
    status["scopes"]["detail"]["running"] = True
    assert not idle.idle_status_safe(status)
    status["scopes"]["detail"] = {}
    assert not idle.idle_status_safe(status)


def test_cleanup_failure_does_not_interrupt_solver_loop(monkeypatch):
    controller, backend, _now = setup_idle(monkeypatch)

    def failed_close():
        raise OSError("test display closed")

    backend.close = failed_close
    assert controller.tick(SAFE, lambda: SAFE)["kind"] == "idle_pointer_move"
    assert controller.last_move is None
