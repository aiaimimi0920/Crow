import random
import sys
import time
import types

from src import captcha_solver
from tools.test.captcha_solver_test_context import set_solver_platform


def test_os_drag_rejects_x11_mapping_when_cursor_does_not_reach_slider(monkeypatch) -> None:
    class FakePyAutoGUI:
        FAILSAFE = True
        PAUSE = 0

        @staticmethod
        def position():
            return (0.0, 0.0)

        @staticmethod
        def moveTo(_x, _y, duration=0):
            return None

        def __getattr__(self, name):
            raise AssertionError(f"unexpected pyautogui call: {name}")

    set_solver_platform(monkeypatch, "posix")
    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI())
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._focus_os_window = lambda: True
    solver._ensure_os_left_button_released = lambda _mapped: True
    solver._map_css_to_screen = lambda *_args, **_kwargs: {
        "x": 100.0,
        "y": 50.0,
        "distance": 260.0,
        "source": "x11_window_geometry",
        "located": True,
        "clipped": False,
    }
    solver._os_drag_profile = lambda _index=0: {
        "name": "test",
        "pre_pause": (0, 0),
        "press_hold": (0, 0),
        "approach_duration": (0, 0),
        "start_duration": (0, 0),
    }

    assert solver._do_drag_os(100, 50, 260, slider_info={"x": 80, "y": 35}) is None
    assert solver.last_failure_reason == "os_cursor_position_unverified"

def test_clamp_search_region_trims_negative_region_to_screen() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    clamped = solver._clamp_search_region((-65, 212, 2177, 1437), (3840, 2160))

    assert clamped == (0, 212, 2112, 1437)

def test_viewport_origin_retries_full_screen_after_regional_locate_miss(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class Box:
        left = 111
        top = 222
        width = 304
        height = 38

    class FakePyAutoGUI:
        @staticmethod
        def size():
            return (1280, 720)

        @staticmethod
        def locateOnScreen(_path, **kwargs):
            calls.append(dict(kwargs))
            if "region" in kwargs:
                if "confidence" in kwargs:
                    return None
                raise ValueError("needle exceeds haystack")
            return Box()

    class FakeImage:
        @staticmethod
        def open(_stream):
            return types.SimpleNamespace(size=(304, 38))

    fake_pil = types.ModuleType("PIL")
    fake_pil.Image = FakeImage
    monkeypatch.setitem(sys.modules, "pyautogui", FakePyAutoGUI())
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._send_cdp = lambda *_args, **_kwargs: {"data": "ZmFrZQ=="}

    located = solver._viewport_origin_on_screen(
        {"x": 567.5, "y": 453.0, "width": 42.0, "height": 30.0, "track_width": 300.0},
        search_region=(500, 500, 100, 100),
        drag_distance=256,
    )

    assert located["left"] == 111.0
    assert located["top"] == 222.0
    assert [call.get("region") for call in calls] == [
        (500, 500, 100, 100),
        (500, 500, 100, 100),
        None,
    ]

def test_os_drag_track_produces_monotonic_eased_steps(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.setattr(random, "uniform", lambda start, end: (start + end) / 2)
    profile = solver._os_drag_profile()

    fracs, dwells = solver._os_drag_track(320, profile)

    assert len(fracs) == len(dwells)
    assert len(fracs) >= profile["steps"][0]
    assert fracs[0] > 0
    assert fracs[-1] == 1.0
    assert all(left < right for left, right in zip(fracs, fracs[1:], strict=False))
    assert all(0.006 <= dwell <= 0.09 for dwell in dwells)

def test_os_drag_release_plan_releases_at_target(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.setattr(random, "uniform", lambda start, end: (start + end) / 2)
    profile = solver._os_drag_profile()

    peak_x, settle_xs, release_x = solver._os_drag_release_plan(100.0, 300.0, profile)

    assert 400.0 <= peak_x <= 401.2
    assert release_x == 400.0
    assert settle_xs
    assert settle_xs[-1] == release_x
    assert all(left >= right for left, right in zip(settle_xs, settle_xs[1:], strict=False))

def test_os_drag_profile_switches_variants_by_index(monkeypatch) -> None:
    set_solver_platform(monkeypatch, "nt")
    solver = captcha_solver.CaptchaSolver(port=9223)

    first = solver._os_drag_profile(0)
    second = solver._os_drag_profile(1)
    third = solver._os_drag_profile(2)

    assert first["name"] == "fast_exact_v3"
    assert second["name"] == "legacy_exact_release"
    assert third["name"] == "dense_exact_release"
    assert first["release_mode"] == "exact_release"
    assert first["total_time"] == (0.4, 0.65)
    assert first["release_overshoot"] == (0.0, 0.0)
    assert second["release_mode"] == "exact_release"
    assert second["warmup_steps"] == (2, 3)

def test_os_drag_warmup_points_respect_profile(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.setattr(random, "uniform", lambda start, end: (start + end) / 2)
    monkeypatch.setattr(random, "gauss", lambda mean, _sigma: mean)
    profile = solver._os_drag_profile(0)

    points = solver._os_drag_warmup_points(100.0, 200.0, profile)

    assert len(points) == 1
    assert points[0][0] == 102.0

def test_nc_retry_click_candidates_prioritize_retry_text_then_widget() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    candidates = solver._nc_retry_click_candidates({
        "retryText": {"x": 10.0, "y": 20.0, "width": 90.0, "height": 30.0},
        "widget": {"x": 100.0, "y": 200.0, "width": 300.0, "height": 40.0},
    })

    assert candidates
    assert candidates[0]["label"] == "widget_centerline"
    assert any(candidate["label"] == "widget_centerline" for candidate in candidates)

def test_reset_failed_nc_challenge_tries_multiple_click_points_until_slider_returns(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    clicks: list[tuple[float, float]] = []
    outcomes = [
        {"authenticated": False},
        {"slider": {"x": 1, "y": 2, "width": 3, "height": 4}},
    ]

    solver._nc_retry_targets = lambda: {
        "retryText": {"x": 10.0, "y": 20.0, "width": 100.0, "height": 30.0},
        "widget": {"x": 200.0, "y": 300.0, "width": 280.0, "height": 40.0},
    }
    solver._click_css_point = lambda x, y, **_kwargs: clicks.append((x, y)) or True
    solver._nc_retry_outcome = lambda timeout_seconds=8.0: outcomes.pop(0)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver._reset_failed_nc_challenge() is True
    assert len(clicks) == 2

def test_nc_retry_outcome_waits_for_three_stable_slider_samples(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    slider_calls = 0

    solver._refresh_challenge_summary = lambda _summary: {}

    def find_slider(**_kwargs):
        nonlocal slider_calls
        slider_calls += 1
        x = 100.0 if slider_calls == 1 else 101.0
        return {"x": x, "y": 200.0, "width": 42.0, "height": 30.0}

    solver._find_slider = find_slider
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    outcome = solver._nc_retry_outcome(timeout_seconds=1.0)

    assert outcome["slider"]["x"] == 101.0
    assert slider_calls == 4
