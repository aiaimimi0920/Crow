import time

from src import captcha_solver


def test_verify_success_rejects_local_mock_retry_then_success_without_manual_required(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=retry_then_success",
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda _method, _params: {
            "result": {
                "value": {
                    "success": False,
                    "successDetected": False,
                    "sliderGone": False,
                    "challengeGone": False,
                    "hasError": True,
                    "noError": False,
                    "mockStateSuccess": False,
                    "mockStateFailure": True,
                    "mockResolution": "failure",
                    "mockStatusText": "验证失败，点击框体重试(error:KzCFR9)",
                    "mockVerifyMode": "retry_then_success",
                    "mockChallengeVisible": True,
                }
            }
        },
    )

    assert solver._verify_success() is False
    assert solver.last_failure_reason is None
    assert solver._last_mock_terminal_state == "terminal_failure"

def test_wait_for_verification_success_short_circuits_local_mock_explicit_fail(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=explicit_fail",
    )
    calls = {"verify": 0, "sleep": 0}

    def fake_verify() -> bool:
        calls["verify"] += 1
        solver._last_mock_terminal_state = "manual_required"
        return False

    monkeypatch.setattr(solver, "_verify_success", fake_verify)
    monkeypatch.setattr(
        solver,
        "_page_challenge_summary",
        lambda: (_ for _ in ()).throw(AssertionError("explicit_fail terminal state should not need page summary")),
    )
    monkeypatch.setattr(time, "sleep", lambda _seconds: calls.__setitem__("sleep", calls["sleep"] + 1))

    assert solver._wait_for_verification_success(max_checks=10) is False
    assert solver.last_failure_reason == "manual_required"
    assert calls == {"verify": 1, "sleep": 0}

def test_wait_for_verification_success_short_circuits_local_mock_near_miss(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=near_miss",
    )
    calls = {"verify": 0, "sleep": 0}

    def fake_verify() -> bool:
        calls["verify"] += 1
        solver._last_mock_terminal_state = "terminal_failure"
        return False

    monkeypatch.setattr(solver, "_verify_success", fake_verify)
    monkeypatch.setattr(
        solver,
        "_page_challenge_summary",
        lambda: (_ for _ in ()).throw(AssertionError("near_miss must not use explicit-fail terminal check")),
    )
    monkeypatch.setattr(time, "sleep", lambda _seconds: calls.__setitem__("sleep", calls["sleep"] + 1))

    assert solver._wait_for_verification_success(max_checks=3) is False
    assert solver.last_failure_reason is None
    assert calls == {"verify": 1, "sleep": 0}

def test_wait_for_verification_success_short_circuits_local_mock_retry_then_success(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=retry_then_success",
    )
    calls = {"verify": 0, "sleep": 0}

    def fake_verify() -> bool:
        calls["verify"] += 1
        solver._last_mock_terminal_state = "terminal_failure"
        return False

    monkeypatch.setattr(solver, "_verify_success", fake_verify)
    monkeypatch.setattr(
        solver,
        "_page_challenge_summary",
        lambda: (_ for _ in ()).throw(AssertionError("retry_then_success must not force manual-required summary checks")),
    )
    monkeypatch.setattr(time, "sleep", lambda _seconds: calls.__setitem__("sleep", calls["sleep"] + 1))

    assert solver._wait_for_verification_success(max_checks=5) is False
    assert solver.last_failure_reason is None
    assert calls == {"verify": 1, "sleep": 0}

def test_wait_for_verification_success_keeps_polling_local_mock_without_terminal_state(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=strict_success_text",
    )
    calls = {"verify": 0, "sleep": 0}

    def fake_verify() -> bool:
        calls["verify"] += 1
        solver._last_mock_terminal_state = None
        return False

    monkeypatch.setattr(solver, "_verify_success", fake_verify)
    monkeypatch.setattr(time, "sleep", lambda _seconds: calls.__setitem__("sleep", calls["sleep"] + 1))

    assert solver._wait_for_verification_success(max_checks=3) is False
    assert calls == {"verify": 10, "sleep": 9}

def test_solver_returns_immediately_when_local_mock_wait_sets_manual_required(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=explicit_fail",
    )
    calls = {"reload": 0}

    class FakeWebSocket:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        solver,
        "_preflight_current_challenge",
        lambda: {
            "connected": False,
            "manual_required": False,
            "has_slider": False,
            "already_authenticated": False,
        },
    )
    monkeypatch.setattr(solver, "connect_tab", lambda: setattr(solver, "ws", FakeWebSocket()) or True)
    monkeypatch.setattr(solver, "_bring_to_front", lambda: True)
    monkeypatch.setattr(
        solver,
        "_find_slider",
        lambda: {
            "x": 100,
            "y": 200,
            "width": 38,
            "height": 38,
            "selector": "#mock-slider-handle",
            "context": "main",
        },
    )
    monkeypatch.setattr(solver, "_get_track_width", lambda: 420)
    monkeypatch.setattr(solver, "_do_drag_local_mock", lambda _x, _y, distance: distance)

    def fake_wait() -> bool:
        solver.last_failure_reason = "manual_required"
        return False

    monkeypatch.setattr(solver, "_wait_for_verification_success", fake_wait)
    monkeypatch.setattr(
        solver,
        "_page_challenge_summary",
        lambda: (_ for _ in ()).throw(AssertionError("challenge summary should not run after terminal manual_required")),
    )
    monkeypatch.setattr(solver, "_reload_page", lambda: calls.__setitem__("reload", calls["reload"] + 1))
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "manual_required"
    assert calls == {"reload": 0}

def test_solver_local_mock_retry_then_success_replays_without_spending_main_attempt(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=retry_then_success",
    )
    calls = {"connect": 0, "drag": 0, "reset": 0, "verify": 0}
    verify_results = [False, True]

    monkeypatch.setattr(
        solver,
        "_preflight_current_challenge",
        lambda: {
            "connected": True,
            "manual_required": False,
            "has_slider": True,
            "already_authenticated": False,
        },
    )
    monkeypatch.setattr(solver, "connect_tab", lambda: calls.__setitem__("connect", calls["connect"] + 1) or True)
    monkeypatch.setattr(solver, "_bring_to_front", lambda: True)
    monkeypatch.setattr(
        solver,
        "_find_slider",
        lambda: {
            "x": 100,
            "y": 200,
            "width": 38,
            "height": 38,
            "selector": "#mock-slider-handle",
            "context": "main",
        },
    )
    monkeypatch.setattr(solver, "_get_track_width", lambda: 420)
    monkeypatch.setattr(
        solver,
        "_do_drag_local_mock",
        lambda _x, _y, distance: calls.__setitem__("drag", calls["drag"] + 1) or distance,
    )
    monkeypatch.setattr(
        solver,
        "_wait_for_verification_success",
        lambda: calls.__setitem__("verify", calls["verify"] + 1) or verify_results.pop(0),
    )
    monkeypatch.setattr(
        solver,
        "_reset_failed_nc_challenge",
        lambda: calls.__setitem__("reset", calls["reset"] + 1) or True,
    )
    summaries = [
        {"authenticatedPage": False, "explicitFailure": True, "hasSlider": False},
        {"authenticatedPage": True, "explicitFailure": False, "hasSlider": False},
    ]
    monkeypatch.setattr(solver, "_page_challenge_summary", lambda: summaries.pop(0))
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is True
    assert calls == {"connect": 1, "drag": 2, "reset": 1, "verify": 2}
    assert solver.last_failure_reason is None

def test_solver_near_miss_reloads_and_exhausts_attempts_without_manual_required(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=near_miss",
    )
    calls = {"reload": 0}

    class FakeWebSocket:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        solver,
        "_preflight_current_challenge",
        lambda: {
            "connected": False,
            "manual_required": False,
            "has_slider": False,
            "already_authenticated": False,
        },
    )
    monkeypatch.setattr(solver, "connect_tab", lambda: setattr(solver, "ws", FakeWebSocket()) or True)
    monkeypatch.setattr(solver, "_bring_to_front", lambda: True)
    monkeypatch.setattr(
        solver,
        "_find_slider",
        lambda: {
            "x": 100,
            "y": 200,
            "width": 38,
            "height": 38,
            "selector": "#mock-slider-handle",
            "context": "main",
        },
    )
    monkeypatch.setattr(solver, "_get_track_width", lambda: 420)
    monkeypatch.setattr(solver, "_do_drag_local_mock", lambda _x, _y, distance: distance)
    monkeypatch.setattr(solver, "_wait_for_verification_success", lambda: False)
    monkeypatch.setattr(solver, "_page_challenge_summary", lambda: {"explicitFailure": False})
    monkeypatch.setattr(solver, "_reload_page", lambda: calls.__setitem__("reload", calls["reload"] + 1))
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "max_attempts_exceeded"
    assert calls == {"reload": 1}

def test_os_mouse_disabled_during_pytest() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    assert solver._os_mouse_enabled() is False

def test_live_solve_uses_os_mouse_when_enabled(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    calls: list[str] = []
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._os_mouse_enabled = lambda: True
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag_os = lambda _x, _y, _d, **_k: calls.append("os") or 250
    solver._do_drag = lambda _x, _y, _d: calls.append("cdp") or 250
    solver._wait_for_verification_success = lambda: True
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    assert solver.solve(max_attempts=1) is True
    assert calls == ["os"]

def test_live_solve_does_not_fall_back_to_cdp_after_unverified_screen_mapping(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    calls = {"os": 0, "cdp": 0, "reload": 0}
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._os_mouse_enabled = lambda: True
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._get_track_rect = lambda: None

    def fail_os_drag(_x, _y, _distance, **_kwargs):
        calls["os"] += 1
        solver.last_failure_reason = "screen_mapping_unverified"
        return None

    solver._do_drag_os = fail_os_drag
    solver._do_drag = lambda *_args: calls.__setitem__("cdp", calls["cdp"] + 1)
    solver._reload_page = lambda: calls.__setitem__("reload", calls["reload"] + 1)
    solver._recover_authenticated_list_page = lambda: False
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert calls == {"os": 1, "cdp": 0, "reload": 1}

def test_wait_for_verification_success_accepts_authenticated_auction_page(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    solver._verify_success = lambda: False
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": True,
        "hasSlider": False,
        "explicitFailure": False,
    }
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    assert solver._wait_for_verification_success(max_checks=2) is True

def test_solve_treats_authenticated_page_after_drag_as_success(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver.connect_tab = lambda: True
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._os_mouse_enabled = lambda: False
    solver._do_drag = lambda _x, _y, _d: 250
    solver._wait_for_verification_success = lambda: False
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": True,
        "explicitFailure": False,
        "hasSlider": False,
    }
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    assert solver.solve(max_attempts=1) is True
    assert solver.last_failure_reason is None

def test_map_css_to_screen_uses_screenshot_when_near_win32() -> None:
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
        "left": 146.0,
        "top": 116.0,
        "width": 360.0,
        "height": 48.0,
        "shot_w": 360.0,
        "shot_h": 48.0,
        "clipped": True,
        "clip_x": 80.0,
        "clip_y": 30.0,
        "clip_w": 300.0,
        "clip_h": 40.0,
    }
    mapped = solver._map_css_to_screen(100, 50, 260)
    assert mapped["source"] == "screenshot_handle"
    assert abs(mapped["x"] - 170.0) < 0.01
    assert abs(mapped["y"] - 140.0) < 0.01
    assert abs(mapped["distance"] - 312.0) < 0.01
