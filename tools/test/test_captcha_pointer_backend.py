"""Pointer boundary tests use injected devices; never send real input events."""

import ctypes
import sys
from ctypes import wintypes

import pytest

from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_pointer_backend import (
    PyAutoGUIPointerBackend,
    UInputPointerBackend,
    Win32PointerBackend,
)
from src.captcha_solver import CaptchaSolver


class FakePointer:
    supports_duration = False

    def __init__(self):
        self.xy = (0.0, 0.0)
        self.moves = []
        self.buttons = []

    def position(self):
        return self.xy

    def move(self, x, y, duration=0):
        self.xy = (x, y)
        self.moves.append((x, y, duration))

    def left_button(self, *, down):
        self.buttons.append(down)


class FakeWin32:
    def __init__(self, *, can_set=True, can_read=True):
        self.can_set = can_set
        self.can_read = can_read
        self.xy = (12, 34)
        self.events = []
        self.metrics = {76: -1920, 77: -1080, 78: 3840, 79: 2160}

    def GetCursorPos(self, value):
        point = ctypes.cast(value, ctypes.POINTER(wintypes.POINT)).contents
        point.x, point.y = self.xy
        return self.can_read

    def SetCursorPos(self, x, y):
        self.xy = (x, y)
        return self.can_set

    def GetSystemMetrics(self, index):
        return self.metrics[index]

    def mouse_event(self, *event):
        self.events.append(event)


def test_win32_direct_position_and_button_transitions():
    api = FakeWin32()
    backend = Win32PointerBackend(api)
    assert backend.position() == (12.0, 34.0)
    backend.move(10.7, -12.2)
    assert api.xy == (11, -12)
    assert not api.events
    backend.left_button(down=True)
    backend.left_button(down=False)
    assert api.events == [(0x0002, 0, 0, 0, 0), (0x0004, 0, 0, 0, 0)]


def test_win32_absolute_fallback_uses_virtual_desktop_and_clamps():
    api = FakeWin32(can_set=False)
    backend = Win32PointerBackend(api)
    backend.move(-1920, -1080)
    backend.move(1919, 1079)
    backend.move(-9999, 9999)
    assert api.events == [
        (0xC001, 0, 0, 0, 0),
        (0xC001, 65535, 65535, 0, 0),
        (0xC001, 0, 65535, 0, 0),
    ]
    with pytest.raises(OSError, match="GetCursorPos failed"):
        Win32PointerBackend(FakeWin32(can_read=False)).position()


def test_backend_selection_is_lazy_and_preserves_platform_choice(monkeypatch):
    solver = CaptchaSolver()
    mouse = FakePointer()
    monkeypatch.setattr(solver, "_native_os_input_enabled", lambda: False)
    monkeypatch.setattr(solver, "_uinput_os_input_enabled", lambda: False)
    assert isinstance(solver._os_pointer_backend(mouse), PyAutoGUIPointerBackend)
    monkeypatch.setattr(solver, "_native_os_input_enabled", lambda: True)
    assert isinstance(solver._os_pointer_backend(mouse), Win32PointerBackend)
    monkeypatch.setattr(solver, "_native_os_input_enabled", lambda: False)
    monkeypatch.setattr(solver, "_uinput_os_input_enabled", lambda: True)
    monkeypatch.setattr(
        solver, "_get_uinput_handle", lambda: pytest.fail("device opened")
    )
    assert isinstance(solver._os_pointer_backend(mouse), UInputPointerBackend)


def test_injected_backend_preserves_bounded_timing(monkeypatch):
    pointer = FakePointer()
    solver = CaptchaSolver(pointer_backend=pointer)
    waits = []
    monkeypatch.setattr(solver, "_wait_interruptibly", waits.append)
    solver._move_os_cursor_timed(None, 200.0, 100.0, 0.4)
    assert solver._get_os_cursor_position(None) == (200.0, 100.0)
    assert 3 <= len(pointer.moves) <= 12
    assert all(duration == 0 for _, _, duration in pointer.moves)
    assert sum(waits) == pytest.approx(0.4)


def test_interrupted_injected_drag_releases_button_without_device_import(monkeypatch):
    pointer = FakePointer()
    solver = CaptchaSolver(pointer_backend=pointer)
    monkeypatch.setitem(sys.modules, "pyautogui", None)
    monkeypatch.setattr(solver, "_uinput_os_input_enabled", lambda: True)
    monkeypatch.setattr(
        solver, "_get_uinput_handle", lambda: pytest.fail("device opened")
    )
    monkeypatch.setattr(solver, "_enable_process_dpi_awareness", lambda: None)
    monkeypatch.setattr(solver, "_focus_os_window", lambda: True)
    monkeypatch.setattr(solver, "_wait_interruptibly", lambda _: None)
    monkeypatch.setattr(
        solver,
        "_map_css_to_screen",
        lambda *a, **kw: {
            "x": 10,
            "y": 20,
            "distance": 30,
            "source": "fake",
            "located": True,
        },
    )
    monkeypatch.setattr(solver, "_os_drag_warmup_points", lambda *a: [(11, 20)])
    monkeypatch.setattr(solver, "_stop_if_cancelled", lambda: True)
    assert solver._do_drag_os(10, 20, 30) is None
    assert solver.last_failure_reason == "cancelled"
    assert pointer.buttons == [True, False]


def test_uinput_nonconvergence_fails_closed(monkeypatch):
    solver = CaptchaSolver()
    mouse = FakePointer()

    class Device:
        def write(self, *event):
            pass

        def syn(self):
            pass

    class Codes:
        EV_REL, REL_X, REL_Y = 2, 0, 1

    solver._uinput_ecodes = Codes
    monkeypatch.setattr(solver, "_get_uinput_handle", lambda: Device())
    monkeypatch.setattr(solver, "_native_os_input_enabled", lambda: False)
    monkeypatch.setattr(solver, "_uinput_os_input_enabled", lambda: True)
    waits = []
    monkeypatch.setattr(solver, "_wait_interruptibly", waits.append)
    with pytest.raises(RuntimeError, match="did not converge"):
        solver._set_os_cursor_position(mouse, 200, 100)
    assert solver.last_failure_reason == "os_cursor_position_unverified"
    assert len(waits) == 36


@pytest.mark.parametrize("reason", ["deadline_exceeded", "cancelled"])
def test_wait_stop_releases_button_and_reaches_budget_cleanup(monkeypatch, reason):
    pointer = FakePointer()
    solver = CaptchaSolver(pointer_backend=pointer)
    now = [0.0]
    budget = SolveBudget(deadline=100, clock=lambda: now[0])
    closed = []

    def wait(_seconds):
        if pointer.buttons == [True]:
            if reason == "cancelled":
                budget.event.set()
            else:
                now[0] = 101
            budget.wait(0)

    monkeypatch.setitem(sys.modules, "pyautogui", None)
    monkeypatch.setattr(solver, "_enable_process_dpi_awareness", lambda: None)
    monkeypatch.setattr(solver, "_focus_os_window", lambda: True)
    monkeypatch.setattr(solver, "_wait_interruptibly", wait)
    monkeypatch.setattr(
        solver,
        "_map_css_to_screen",
        lambda *a, **kw: {
            "x": 10,
            "y": 20,
            "distance": 30,
            "source": "fake",
            "located": True,
        },
    )
    monkeypatch.setattr(solver, "_close_solver_ws", lambda: closed.append("ws"))
    monkeypatch.setattr(
        solver, "_close_owned_target_tabs", lambda: closed.append("tabs")
    )
    with pytest.raises(SolveStopped), budget.scope(solver):
        solver._do_drag_os(10, 20, 30)
    assert pointer.buttons == [True, False]
    assert solver.last_failure_reason == reason
    assert closed == ["ws", "tabs"]
    assert not solver.lock.locked()
    assert solver._solve_budget is None


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows boundary")
def test_win32_uninjected_backend_rejects_non_windows_without_device_access():
    backend = Win32PointerBackend()
    assert backend._api is None
    with pytest.raises(OSError, match="requires Windows"):
        _ = backend.api
    assert backend._api is None


def test_win32_injected_backend_does_not_require_platform_loader():
    api = FakeWin32()
    backend = Win32PointerBackend(api)
    assert backend.api is api
    assert backend.position() == (12.0, 34.0)
