import time

from src import captcha_solver


def test_preflight_keeps_connected_target_while_slider_is_still_loading() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    class FakeWebSocket:
        closed = False

        def close(self) -> None:
            self.closed = True

    ws = FakeWebSocket()
    solver.ws = ws
    solver.connect_tab = lambda: True
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "explicitFailure": False,
        "hasSlider": False,
        "loginRequired": False,
        "authenticatedPage": False,
    }

    result = solver._preflight_current_challenge()

    assert result == {
        "connected": True,
        "manual_required": False,
        "has_slider": False,
        "already_authenticated": False,
    }
    assert ws.closed is False
    assert solver.ws is ws


def test_solver_uses_existing_cdp_connection_when_slider_appears_after_preflight(
    monkeypatch,
) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    class FakeWebSocket:
        def close(self) -> None:
            return None

    solver.ws = FakeWebSocket()
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": False,
        "already_authenticated": False,
    }
    solver._headed_playwright_enabled = lambda: True
    solver._solve_with_ddddocr = lambda: (_ for _ in ()).throw(
        AssertionError("connected CDP target must skip independent headed fallback")
    )
    solver._solve_with_playwright_stealth = lambda: (_ for _ in ()).throw(
        AssertionError("connected CDP target must skip independent headed fallback")
    )
    solver.connect_tab = lambda: (_ for _ in ()).throw(
        AssertionError("first attempt must preserve the preflight CDP connection")
    )
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100,
        "y": 200,
        "width": 38,
        "height": 38,
        "selector": "#nc_1_n1z",
        "context": "main",
    }
    solver._get_track_width = lambda: 420
    solver._get_track_rect = lambda: None
    solver._os_mouse_enabled = lambda: False
    solver._do_drag = lambda _x, _y, distance: distance
    solver._wait_for_verification_success = lambda: True
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is True
