import ctypes
import subprocess
import sys
import time

from src import captcha_solver
from tools.test.captcha_solver_test_context import set_solver_platform


def test_linux_map_rejects_far_clipped_match_without_viewport_confirmation(monkeypatch) -> None:
    set_solver_platform(monkeypatch, "posix")
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._target_activation_verified = True
    solver._css_to_client_screen = lambda *_args: {
        "x": 592.0,
        "y": 596.0,
        "distance": 256.0,
        "source": "dpr_fallback",
    }
    solver._css_to_cdp_window_screen = lambda *_args: None

    def locate(slider_info, **_kwargs):
        if slider_info is None:
            return None
        return {
            "left": 4.0,
            "top": 124.0,
            "width": 304.0,
            "height": 38.0,
            "clipped": True,
            "clip_x": 565.5,
            "clip_y": 449.0,
            "clip_w": 304.0,
            "clip_h": 38.0,
        }

    solver._viewport_origin_on_screen = locate

    assert solver._map_css_to_screen(
        588,
        468,
        256,
        slider_info={"x": 567.5, "y": 453.0, "width": 42.0, "height": 30.0},
    ) is None
    assert solver.last_failure_reason == "screen_mapping_unverified"

def test_prune_challenge_tabs_keeps_only_requested_target_route() -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    )
    closed = []
    solver._close_cdp_target = lambda target_id: closed.append(target_id) or True

    tabs = [
        {
            "type": "page",
            "id": "keep",
            "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5secdata=a",
            "webSocketDebuggerUrl": "ws://keep",
        },
        {
            "type": "page",
            "id": "duplicate",
            "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5secdata=b",
            "webSocketDebuggerUrl": "ws://duplicate",
        },
        {
            "type": "page",
            "id": "other-route",
            "url": "https://sf.taobao.com/list/50025970__2.htm/_____tmd_____/punish?x5secdata=c",
            "webSocketDebuggerUrl": "ws://other-route",
        },
        {
            "type": "page",
            "id": "login",
            "url": "https://login.taobao.com/havanaone/login/login.htm",
            "webSocketDebuggerUrl": "ws://login",
        },
        {
            "type": "page",
            "id": "auction",
            "url": "https://sf.taobao.com/list/50025970__2.htm",
            "webSocketDebuggerUrl": "ws://auction",
        },
    ]

    result = solver._prune_duplicate_challenge_tabs(tabs)

    assert result == {"closed": 2, "kept": "keep"}
    assert closed == ["duplicate", "other-route"]

def test_map_css_to_screen_allows_zero_distance_for_clicks() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._css_to_client_screen = lambda *_args: {
        "x": 120.0,
        "y": 80.0,
        "distance": 0.0,
        "source": "test",
    }
    solver._css_to_cdp_window_screen = lambda *_args: None
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: None

    mapped = solver._map_css_to_screen(100, 50, 0, allow_zero_distance=True)

    assert mapped is not None
    assert mapped["x"] == 120.0
    assert mapped["y"] == 80.0
    assert mapped["distance"] == 0.0

def test_click_css_point_falls_back_to_cdp_when_os_mapping_is_unavailable(monkeypatch) -> None:
    class FakePyAutoGUI:
        FAILSAFE = True
        PAUSE = 0

    dispatched: list[str] = []
    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI())
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._os_mouse_enabled = lambda: True
    solver._focus_os_window = lambda: True
    solver._map_css_to_screen = lambda *_args, **_kwargs: None
    solver._dispatch_mouse = lambda event, *_args, **_kwargs: dispatched.append(event) or True

    assert solver._click_css_point(100, 50) is True
    assert dispatched == ["mousePressed", "mouseReleased"]

def test_bounded_os_cursor_move_uses_fixed_zero_duration_steps(monkeypatch) -> None:
    moves: list[tuple[float, float, float]] = []
    sleeps: list[float] = []

    class FakePyAutoGUI:
        def position(self):
            return (0.0, 0.0)

        def moveTo(self, x, y, duration=0):
            moves.append((x, y, duration))

    monkeypatch.setattr(time, "sleep", sleeps.append)
    solver = captcha_solver.CaptchaSolver(port=9223)

    solver._move_os_cursor_bounded(FakePyAutoGUI(), 100.0, 50.0, 0.4)

    assert 3 <= len(moves) <= 12
    assert all(duration == 0 for _x, _y, duration in moves)
    assert moves[-1][:2] == (100.0, 50.0)
    assert abs(sum(sleeps) - 0.4) < 0.001

def test_timed_os_cursor_move_preserves_pyautogui_duration_by_default(monkeypatch) -> None:
    moves: list[tuple[float, float, float]] = []

    class FakePyAutoGUI:
        def moveTo(self, x, y, duration=0):
            moves.append((x, y, duration))

    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.delenv("FAPAI_SOLVER_OS_INPUT_BACKEND", raising=False)

    solver._move_os_cursor_timed(FakePyAutoGUI(), 100.0, 50.0, 0.4)

    assert moves == [(100.0, 50.0, 0.4)]

def test_native_os_input_requires_explicit_opt_in(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    set_solver_platform(monkeypatch, "nt")
    monkeypatch.delenv("FAPAI_SOLVER_OS_INPUT_BACKEND", raising=False)

    assert solver._native_os_input_enabled() is False

    monkeypatch.setenv("FAPAI_SOLVER_OS_INPUT_BACKEND", "win32")
    assert solver._native_os_input_enabled() is True

def test_linux_uinput_requires_explicit_opt_in(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    set_solver_platform(monkeypatch, "posix")
    monkeypatch.delenv("FAPAI_SOLVER_OS_INPUT_BACKEND", raising=False)

    assert solver._uinput_os_input_enabled() is False

    monkeypatch.setenv("FAPAI_SOLVER_OS_INPUT_BACKEND", "uinput")
    assert solver._uinput_os_input_enabled() is True

def test_uinput_moves_with_cursor_feedback_and_emits_button_events(monkeypatch) -> None:
    class Codes:
        EV_REL = 2
        EV_KEY = 1
        REL_X = 0
        REL_Y = 1
        BTN_LEFT = 272

    class FakePyAutoGUI:
        x = 0.0
        y = 0.0

        def position(self):
            return (self.x, self.y)

    class FakeHandle:
        def __init__(self, mouse):
            self.mouse = mouse
            self.events = []

        def write(self, event_type, code, value):
            self.events.append((event_type, code, value))
            if event_type == Codes.EV_REL and code == Codes.REL_X:
                self.mouse.x += value * 0.25
            if event_type == Codes.EV_REL and code == Codes.REL_Y:
                self.mouse.y += value * 0.25

        def syn(self):
            self.events.append(("syn",))

    set_solver_platform(monkeypatch, "posix")
    monkeypatch.setenv("FAPAI_SOLVER_OS_INPUT_BACKEND", "uinput")
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    mouse = FakePyAutoGUI()
    handle = FakeHandle(mouse)
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._uinput_handle = handle
    solver._uinput_ecodes = Codes

    solver._move_uinput_cursor_to(mouse, 200.0, 100.0)
    solver._set_os_left_button(mouse, down=True)
    solver._set_os_left_button(mouse, down=False)

    assert abs(mouse.x - 200.0) <= 1.25
    assert abs(mouse.y - 100.0) <= 1.25
    assert (Codes.EV_KEY, Codes.BTN_LEFT, 1) in handle.events
    assert (Codes.EV_KEY, Codes.BTN_LEFT, 0) in handle.events

def test_linux_window_focus_activates_visible_chromium(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    activations: list[bool] = []

    class Result:
        def __init__(self, *, stdout="", returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(command, **_kwargs):
        calls.append(tuple(command))
        if command[1] == "search":
            return Result(stdout="101\n" if command[-1] == "chromium" else "")
        if command[1] == "getwindowfocus":
            return Result(stdout="101\n" if any(call[1] == "windowactivate" for call in calls) else "")
        return Result()

    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(solver, "_activate_target_tab", lambda: activations.append(True) or True)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert solver._focus_linux_window() is True
    assert ("xdotool", "windowactivate", "--sync", "101") in calls
    assert activations == [True, True]
    assert solver._linux_window_id == "101"

def test_linux_window_focus_fails_when_exact_target_cannot_be_reactivated(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    class Result:
        def __init__(self, *, stdout="", returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(command, **_kwargs):
        calls.append(tuple(command))
        if command[1] == "search":
            return Result(stdout="101\n" if command[-1] == "chromium" else "")
        if command[1] == "getwindowfocus":
            return Result(stdout="101\n" if any(call[1] == "windowactivate" for call in calls) else "")
        return Result()

    activations = iter((True, False))
    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(solver, "_activate_target_tab", lambda: next(activations))
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert solver._focus_linux_window() is False
    assert ("xdotool", "windowactivate", "--sync", "101") in calls

def test_linux_window_focus_requires_display(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("xdotool must not run")),
    )

    assert solver._focus_linux_window() is False

def test_set_os_cursor_position_falls_back_to_absolute_mouse_event(monkeypatch) -> None:
    events: list[tuple[object, ...]] = []

    class FakeUser32:
        @staticmethod
        def SetCursorPos(x, y):
            events.append(("set", x, y))
            return 0

        @staticmethod
        def GetSystemMetrics(index):
            return {76: 0, 77: 0, 78: 1920, 79: 1080}[index]

        @staticmethod
        def mouse_event(flags, x, y, data, extra_info):
            events.append(("mouse_event", flags, x, y, data, extra_info))

    class FakeWindll:
        user32 = FakeUser32()

    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.setattr(solver, "_native_os_input_enabled", lambda: True)
    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)

    solver._set_os_cursor_position(object(), 960, 540)

    assert events[0] == ("set", 960, 540)
    assert events[1][0] == "mouse_event"
    assert events[1][1] == 0x0001 | 0x4000 | 0x8000
    assert 32760 <= int(events[1][2]) <= 32810
    assert 32760 <= int(events[1][3]) <= 32820

def test_os_drag_skips_when_window_focus_fails(monkeypatch) -> None:
    class FakePyAutoGUI:
        FAILSAFE = True
        PAUSE = 0

        def __getattr__(self, name):
            raise AssertionError(f"unexpected pyautogui call: {name}")

    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI())
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._focus_os_window = lambda: False

    assert solver._do_drag_os(100, 50, 260) is None
    assert solver.last_failure_reason == "window_focus_failed"

def test_os_drag_handles_window_focus_exception(monkeypatch) -> None:
    class FakePyAutoGUI:
        FAILSAFE = True
        PAUSE = 0

        def __getattr__(self, name):
            raise AssertionError(f"unexpected pyautogui call: {name}")

    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI())
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._focus_os_window = lambda: (_ for _ in ()).throw(RuntimeError("focus API failed"))

    assert solver._do_drag_os(100, 50, 260) is None
    assert solver.last_failure_reason == "window_focus_failed"

def test_os_drag_releases_mouse_after_move_exception(monkeypatch) -> None:
    calls: list[str] = []

    class FakePyAutoGUI:
        FAILSAFE = True
        PAUSE = 0

        def moveTo(self, *_args, **_kwargs):
            calls.append("move")
            if calls.count("move") == 3:
                raise RuntimeError("move failed")

        def mouseDown(self):
            calls.append("down")

        def mouseUp(self):
            calls.append("up")

    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI())
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._focus_os_window = lambda: True
    solver._map_css_to_screen = lambda *_args, **_kwargs: {
        "x": 100.0, "y": 50.0, "distance": 260.0, "source": "test",
        "located": False, "clipped": False,
    }
    solver._os_drag_profile = lambda _index=0: {
        "name": "test", "pre_pause": (0, 0), "press_hold": (0, 0),
        "approach_duration": (0, 0), "start_duration": (0, 0),
    }
    solver._os_drag_warmup_points = lambda *_args: []
    solver._os_drag_track = lambda *_args: ([0.5], [0])

    assert solver._do_drag_os(100, 50, 260) is None
    assert solver.last_failure_reason == "mouse_drag_exception"
    assert calls[-1] == "up"

def test_os_drag_skips_unverified_slider_screen_mapping(monkeypatch) -> None:
    class FakePyAutoGUI:
        FAILSAFE = True
        PAUSE = 0

        def __getattr__(self, name):
            raise AssertionError(f"unexpected pyautogui call: {name}")

    map_calls: list[bool] = []
    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI())
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._focus_os_window = lambda: True

    def unverified_map(*_args, **_kwargs):
        map_calls.append(True)
        return {
            "x": 100.0,
            "y": 50.0,
            "distance": 260.0,
            "source": "test",
            "located": False,
            "clipped": False,
        }

    solver._map_css_to_screen = unverified_map

    assert solver._do_drag_os(100, 50, 260, slider_info={"x": 80, "y": 35}) is None
    assert solver.last_failure_reason == "screen_mapping_unverified"
    assert len(map_calls) == 3
