import json
import random
import time

from src import captcha_solver


def test_legacy_exact_release_profile_settles_back_to_exact_target(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    profile = solver._os_drag_profiles()[1]

    assert profile["name"] == "legacy_exact_release"
    assert profile["warmup_steps"] == (2, 3)

    monkeypatch.setattr(random, "uniform", lambda low, _high: low)
    peak_x, settle_xs, release_x = solver._os_drag_release_plan(100, 256, profile)

    assert peak_x == 360
    assert settle_xs[-1] == 356
    assert release_x == 356

def test_solver_recovers_auth_when_list_page_is_accessible_after_attempts(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver.connect_tab = lambda: True
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: None
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "hardBlock": False,
        "loginRequired": False,
        "hasSlider": False,
        "explicitFailure": False,
    }
    solver._reload_page = lambda: None
    solver._recover_authenticated_list_page = lambda: True
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    assert solver.solve(max_attempts=1) is True
    assert solver.last_failure_reason is None

def test_solver_waits_for_delayed_verification_success_before_reloading(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    calls = {"connect": 0, "drag": 0, "reload": 0, "verify": 0}
    verify_results = [False, False, True]

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    def fake_verify() -> bool:
        calls["verify"] += 1
        return verify_results.pop(0)

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100,
        "y": 100,
        "width": 40,
        "height": 40,
        "selector": "#nc_1_n1z",
        "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag = lambda _x, _y, _distance: calls.__setitem__("drag", calls["drag"] + 1) or _distance
    solver._verify_success = fake_verify
    solver._reload_page = lambda: calls.__setitem__("reload", calls["reload"] + 1)
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "hasSlider": True,
        "explicitFailure": False,
        "title": "验证码拦截",
        "className": "",
        "bodyText": "",
    }
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is True
    assert calls == {"connect": 1, "drag": 1, "reload": 0, "verify": 3}

def test_solve_skips_injected_fallbacks_for_local_mock_slider_target(monkeypatch) -> None:
    target_url = "file:///tmp/mock_slider.html"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

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
    monkeypatch.setattr(solver, "_headed_playwright_enabled", lambda: True)
    monkeypatch.setattr(
        solver,
        "_solve_with_ddddocr",
        lambda: (_ for _ in ()).throw(AssertionError("ddddocr fallback must be skipped")),
    )
    monkeypatch.setattr(
        solver,
        "_solve_with_playwright_stealth",
        lambda: (_ for _ in ()).throw(AssertionError("playwright stealth fallback must be skipped")),
    )
    monkeypatch.setattr(
        solver,
        "_solve_with_userscript",
        lambda: (_ for _ in ()).throw(AssertionError("userscript fallback must be skipped")),
    )
    monkeypatch.setattr(
        solver,
        "connect_tab",
        lambda: setattr(solver, "ws", FakeWebSocket()) or True,
    )
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
    monkeypatch.setattr(solver, "_wait_for_verification_success", lambda: True)
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)

    assert solver.solve(max_attempts=1) is True

def test_local_mock_target_uses_deterministic_drag_distance(monkeypatch) -> None:
    target_url = "file:///tmp/mock_slider.html"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
    dragged_distances: list[float] = []

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
    monkeypatch.setattr(solver, "_headed_playwright_enabled", lambda: True)
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
    monkeypatch.setattr(
        solver,
        "_do_drag_local_mock",
        lambda _x, _y, distance: dragged_distances.append(distance) or distance,
    )
    monkeypatch.setattr(solver, "_wait_for_verification_success", lambda: True)
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        random,
        "uniform",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("local mock path should not use random.uniform")),
    )

    assert solver.solve(max_attempts=1) is True
    assert dragged_distances == [374]

def test_local_mock_target_reloads_without_verifying_after_drag_failure(monkeypatch) -> None:
    target_url = "file:///tmp/mock_slider.html"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
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
    monkeypatch.setattr(solver, "_do_drag_local_mock", lambda *_args: None)
    monkeypatch.setattr(
        solver,
        "_wait_for_verification_success",
        lambda: (_ for _ in ()).throw(AssertionError("verification should not run after drag failure")),
    )
    monkeypatch.setattr(solver, "_reload_page", lambda: calls.__setitem__("reload", calls["reload"] + 1))
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "max_attempts_exceeded"
    assert calls == {"reload": 1}

def test_local_mock_verification_mode_defaults_to_strict_success_text() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="file:///tmp/mock_slider.html")

    assert solver._local_mock_verification_mode() == "strict_success_text"

def test_local_mock_verification_mode_reads_query_parameter() -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=teardown_only",
    )

    assert solver._local_mock_verification_mode() == "teardown_only"

def test_local_mock_verification_mode_accepts_retry_then_success() -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=retry_then_success",
    )

    assert solver._local_mock_verification_mode() == "retry_then_success"

def test_verify_success_accepts_local_mock_strict_success_text(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=strict_success_text",
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda _method, _params: {
            "result": {
                "value": {
                    "success": False,
                    "successDetected": False,
                    "sliderGone": True,
                    "challengeGone": True,
                    "hasError": False,
                    "noError": True,
                    "mockStateSuccess": True,
                    "mockStateFailure": False,
                    "mockResolution": "success",
                    "mockStatusText": "拖动机制验证通过",
                    "mockVerifyMode": "strict_success_text",
                    "mockChallengeVisible": True,
                }
            }
        },
    )

    assert solver._verify_success() is True

def test_verify_success_accepts_local_mock_teardown_only(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=teardown_only",
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda _method, _params: {
            "result": {
                "value": {
                    "success": False,
                    "successDetected": False,
                    "sliderGone": True,
                    "challengeGone": True,
                    "hasError": False,
                    "noError": True,
                    "mockStateSuccess": True,
                    "mockStateFailure": False,
                    "mockResolution": "success",
                    "mockStatusText": "验证组件已关闭",
                    "mockVerifyMode": "teardown_only",
                    "mockChallengeVisible": False,
                }
            }
        },
    )

    assert solver._verify_success() is True

def test_verify_success_rejects_local_mock_explicit_fail(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=explicit_fail",
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda _method, _params: {
            "result": {
                "value": {
                    "success": False,
                    "successDetected": False,
                    "sliderGone": True,
                    "challengeGone": True,
                    "hasError": True,
                    "noError": False,
                    "mockStateSuccess": False,
                    "mockStateFailure": True,
                    "mockResolution": "failure",
                    "mockStatusText": "验证失败，点击框体重试(error:KzCFR9)",
                    "mockVerifyMode": "explicit_fail",
                    "mockChallengeVisible": True,
                }
            }
        },
    )

    assert solver._verify_success() is False
    assert solver._last_mock_terminal_state == "manual_required"

def test_verify_success_rejects_official_failure_after_slider_disappears(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://sf.taobao.com/list/50025969__2.htm",
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda _method, _params: {
            "result": {
                "value": {
                    "success": False,
                    "successDetected": False,
                    "sliderGone": True,
                    "challengeGone": False,
                    "hasError": True,
                    "noError": False,
                }
            }
        },
    )

    assert solver._verify_success() is False

def test_verify_success_rejects_local_mock_near_miss_without_manual_required(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="file:///tmp/mock_slider.html?verifyMode=near_miss",
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda _method, _params: {
            "result": {
                "value": {
                    "success": False,
                    "successDetected": False,
                    "sliderGone": True,
                    "challengeGone": True,
                    "hasError": False,
                    "noError": True,
                    "mockStateSuccess": False,
                    "mockStateFailure": True,
                    "mockResolution": "failure",
                    "mockStatusText": "拖动未达标，请重新拖动",
                    "mockVerifyMode": "near_miss",
                    "mockChallengeVisible": True,
                }
            }
        },
    )

    assert solver._verify_success() is False
    assert solver.last_failure_reason is None
    assert solver._last_mock_terminal_state == "terminal_failure"
