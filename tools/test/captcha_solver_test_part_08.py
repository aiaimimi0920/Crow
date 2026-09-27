from src import captcha_solver
from tools.test.captcha_solver_test_context import set_solver_platform


def test_map_css_to_screen_prefers_render_widget_over_screenshot() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._win32_client_origin = lambda: {
        "hwnd": 1,
        "render_hwnd": 2,
        "left": 50.0,
        "top": 80.0,
        "width": 1920.0,
        "height": 1080.0,
        "uses_render_widget": True,
    }
    solver._window_metrics = lambda: {"innerWidth": 1600, "innerHeight": 900, "dpr": 1.2}
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: {
        "left": 62.0,
        "top": 104.0,
        "width": 48.0,
        "height": 48.0,
        "clipped": True,
        "clip_x": 10.0,
        "clip_y": 20.0,
        "clip_w": 40.0,
        "clip_h": 40.0,
    }
    mapped = solver._map_css_to_screen(100, 50, 260)
    assert mapped["source"] == "win32_render"
    assert abs(mapped["x"] - 170.0) < 0.01
    assert abs(mapped["y"] - 140.0) < 0.01
    assert abs(mapped["distance"] - 312.0) < 0.01

def test_map_css_to_screen_prefers_render_widget_for_moderate_screenshot_drift() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._win32_client_origin = lambda: {
        "hwnd": 1,
        "render_hwnd": 2,
        "left": 50.0,
        "top": 80.0,
        "width": 1920.0,
        "height": 1080.0,
        "uses_render_widget": True,
    }
    solver._window_metrics = lambda: {"innerWidth": 1600, "innerHeight": 900, "dpr": 1.2}
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: {
        "left": 62.0,
        "top": 184.0,
        "width": 48.0,
        "height": 48.0,
        "clipped": True,
        "clip_x": 10.0,
        "clip_y": 20.0,
        "clip_w": 40.0,
        "clip_h": 40.0,
    }

    mapped = solver._map_css_to_screen(100, 50, 260)

    assert mapped["source"] == "win32_render"
    assert abs(mapped["x"] - 170.0) < 0.01
    assert abs(mapped["y"] - 140.0) < 0.01

def test_map_css_to_screen_rejects_screenshot_when_render_widget_delta_is_huge() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._win32_client_origin = lambda: {
        "hwnd": 1,
        "render_hwnd": 2,
        "left": 500.0,
        "top": 400.0,
        "width": 1920.0,
        "height": 1080.0,
        "uses_render_widget": True,
    }
    solver._window_metrics = lambda: {"innerWidth": 1600, "innerHeight": 900, "dpr": 1.2}
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: {
        "left": 0.0,
        "top": 0.0,
        "width": 48.0,
        "height": 48.0,
        "clipped": True,
        "clip_x": 10.0,
        "clip_y": 20.0,
        "clip_w": 40.0,
        "clip_h": 40.0,
    }

    mapped = solver._map_css_to_screen(400, 300, 260)

    assert mapped["source"] == "win32_render"
    assert abs(mapped["x"] - 980.0) < 0.01
    assert abs(mapped["y"] - 760.0) < 0.01

def test_map_css_to_screen_rejects_implausible_screenshot_over_win32() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._win32_client_origin = lambda: {
        "hwnd": 1,
        "left": 50.0,
        "top": 80.0,
        "width": 1920.0,
        "height": 1080.0,
    }
    solver._window_metrics = lambda: {"innerWidth": 1600, "innerHeight": 900, "dpr": 1.2}
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: {
        "left": 0.0,
        "top": 0.0,
        "width": 48.0,
        "height": 48.0,
        "clipped": True,
        "clip_x": 10.0,
        "clip_y": 20.0,
        "clip_w": 40.0,
        "clip_h": 40.0,
    }
    mapped = solver._map_css_to_screen(100, 50, 260)
    assert mapped["source"] == "win32_client"
    assert abs(mapped["x"] - 170.0) < 0.01
    assert abs(mapped["y"] - 140.0) < 0.01

def test_map_css_to_screen_returns_explicit_failure_when_no_mapping_is_available() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._css_to_client_screen = lambda *_args: None
    solver._css_to_cdp_window_screen = lambda *_args: None
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: None

    assert solver._map_css_to_screen(100, 50, 260) is None
    assert solver.last_failure_reason == "screen_mapping_unavailable"

def test_map_css_to_screen_rejects_implausible_screenshot_after_target_activation() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._target_activation_verified = True
    solver._css_to_client_screen = lambda *_args: {
        "x": 320.0,
        "y": 420.0,
        "distance": 256.0,
        "source": "win32_render",
        "uses_render_widget": True,
        "region": (0, 0, 1920, 1080),
    }
    solver._css_to_cdp_window_screen = lambda *_args: None
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: {
        "left": 0.0,
        "top": 0.0,
        "width": 48.0,
        "height": 48.0,
        "clipped": True,
        "clip_x": 10.0,
        "clip_y": 20.0,
        "clip_w": 40.0,
        "clip_h": 40.0,
    }

    mapped = solver._map_css_to_screen(100, 50, 256, slider_info={"x": 80, "y": 35})

    assert mapped["source"] == "win32_render"
    assert abs(mapped["x"] - 320.0) < 0.01
    assert abs(mapped["y"] - 420.0) < 0.01
    assert mapped["located"] is True
    assert mapped["activation_verified"] is True

def test_map_css_to_screen_bounds_template_search_around_expected_slider(monkeypatch) -> None:
    set_solver_platform(monkeypatch, "nt")
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._target_activation_verified = True
    solver._css_to_client_screen = lambda *_args: {
        "x": 592.0,
        "y": 596.0,
        "distance": 256.0,
        "source": "dpr_fallback",
    }
    solver._css_to_cdp_window_screen = lambda *_args: None
    search_regions: list[tuple[int, int, int, int] | None] = []

    def fake_locate(*_args, **kwargs):
        search_regions.append(kwargs.get("search_region"))
        return None

    solver._viewport_origin_on_screen = fake_locate

    mapped = solver._map_css_to_screen(
        588,
        468,
        256,
        slider_info={"x": 567.5, "y": 453.0, "width": 42.0, "height": 30.0},
    )

    assert search_regions == [(496, 516, 490, 190)]
    assert mapped["source"] == "dpr_fallback"
    assert mapped["x"] == 592.0
    assert mapped["y"] == 596.0
    assert mapped["activation_verified"] is True

def test_linux_map_requires_screenshot_match_for_slider(monkeypatch) -> None:
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
    solver._css_to_x11_window_screen = lambda *_args: None
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: None

    assert solver._map_css_to_screen(
        588,
        468,
        256,
        slider_info={"x": 567.5, "y": 453.0, "width": 42.0, "height": 30.0},
    ) is None
    assert solver.last_failure_reason == "screen_mapping_unverified"

def test_linux_x11_mapping_matches_the_exact_cdp_window(monkeypatch) -> None:
    set_solver_platform(monkeypatch, "posix")
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._target_activation_verified = True
    solver._linux_window_id = "101"
    solver._linux_window_geometry = lambda: {
        "x": 0.0,
        "y": 22.0,
        "width": 1440.0,
        "height": 900.0,
    }
    solver._linux_window_frame_extents = lambda: {
        "left": 16.0,
        "right": 16.0,
        "top": 10.0,
        "bottom": 32.0,
    }
    solver._window_metrics = lambda: {
        "innerWidth": 1408,
        "innerHeight": 715,
        "outerWidth": 1440,
        "outerHeight": 900,
        "dpr": 1,
    }
    solver._browser_window_bounds = lambda: {
        "left": 0,
        "top": 22,
        "width": 1440,
        "height": 900,
    }

    mapped = solver._css_to_x11_window_screen(588, 468, 256)

    assert mapped is not None
    assert mapped["source"] == "x11_window_geometry"
    assert mapped["x"] == 604.0
    assert mapped["y"] == 643.0
    assert mapped["distance"] == 256.0
    assert mapped["frame_bottom"] == 32.0

def test_linux_x11_mapping_falls_back_when_frame_extents_are_unavailable(monkeypatch) -> None:
    set_solver_platform(monkeypatch, "posix")
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._target_activation_verified = True
    solver._linux_window_id = "101"
    solver._linux_window_geometry = lambda: {
        "x": 0.0,
        "y": 22.0,
        "width": 1440.0,
        "height": 900.0,
    }
    solver._linux_window_frame_extents = lambda: None
    solver._window_metrics = lambda: {
        "innerWidth": 1408,
        "innerHeight": 715,
        "outerWidth": 1440,
        "outerHeight": 900,
        "dpr": 1,
    }
    solver._browser_window_bounds = lambda: {
        "left": 0,
        "top": 22,
        "width": 1440,
        "height": 900,
    }

    mapped = solver._css_to_x11_window_screen(588, 468, 256)

    assert mapped is not None
    assert mapped["y"] == 675.0
    assert mapped["frame_bottom"] == 0.0

def test_linux_map_accepts_verified_x11_geometry_when_gpu_screenshot_is_opaque(monkeypatch) -> None:
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
    solver._css_to_x11_window_screen = lambda *_args: {
        "x": 604.0,
        "y": 675.0,
        "distance": 256.0,
        "source": "x11_window_geometry",
        "region": (0, 22, 1440, 900),
    }
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("opaque GPU screenshots must not be required")
    )

    mapped = solver._map_css_to_screen(
        588,
        468,
        256,
        slider_info={"x": 567.5, "y": 453.0, "width": 42.0, "height": 30.0},
    )

    assert mapped is not None
    assert mapped["source"] == "x11_window_geometry"
    assert mapped["located"] is True
    assert mapped["activation_verified"] is True

def test_linux_map_trusts_nearby_screenshot_over_dpr_fallback(monkeypatch) -> None:
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
    solver._viewport_origin_on_screen = lambda *_args, **_kwargs: {
        "left": 569.5,
        "top": 577.0,
        "width": 304.0,
        "height": 38.0,
        "clipped": True,
        "clip_x": 565.5,
        "clip_y": 449.0,
        "clip_w": 304.0,
        "clip_h": 38.0,
    }

    mapped = solver._map_css_to_screen(
        588,
        468,
        256,
        slider_info={"x": 567.5, "y": 453.0, "width": 42.0, "height": 30.0},
    )

    assert mapped["source"] == "screenshot_handle"
    assert mapped["x"] == 592.0
    assert mapped["y"] == 596.0
    assert mapped["located"] is True

def test_linux_map_rechecks_full_viewport_after_far_clipped_match(monkeypatch) -> None:
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
    calls: list[object] = []

    def locate(slider_info, **_kwargs):
        calls.append(slider_info)
        if slider_info is not None:
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
        return {
            "left": 4.0,
            "top": 124.0,
            "width": 1431.0,
            "height": 752.0,
            "clipped": False,
            "clip_x": 0.0,
            "clip_y": 0.0,
            "clip_w": 1431.0,
            "clip_h": 752.0,
        }

    solver._viewport_origin_on_screen = locate

    mapped = solver._map_css_to_screen(
        588,
        468,
        256,
        slider_info={"x": 567.5, "y": 453.0, "width": 42.0, "height": 30.0},
    )

    assert calls[0] is not None
    assert calls[1] is None
    assert mapped["source"] == "screenshot_viewport"
    assert mapped["x"] == 592.0
    assert mapped["y"] == 592.0
    assert mapped["located"] is True
