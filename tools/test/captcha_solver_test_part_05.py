import time

from src import captcha_solver


def test_preflight_clears_login_wait_when_page_becomes_authenticated() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.connect_tab = lambda: True
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "explicitFailure": False,
        "hasSlider": False,
        "loginRequired": True,
        "authenticatedPage": False,
        "title": "登录",
        "className": "",
        "bodyText": "请登录后继续",
    }
    solver._poll_until_authenticated = lambda: True

    result = solver._preflight_current_challenge()

    assert result["already_authenticated"] is True
    assert result["manual_required"] is False
    assert solver.last_failure_reason is None

def test_preflight_continues_drag_when_slider_appears_during_login_wait() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.connect_tab = lambda: True
    summaries = [
        {
            "hardBlock": True,
            "explicitFailure": False,
            "hasSlider": False,
            "loginRequired": True,
            "authenticatedPage": False,
            "href": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/page/login_jump",
            "title": "登录跳转",
            "className": "",
            "bodyText": "",
        },
        {
            "hardBlock": True,
            "explicitFailure": False,
            "hasSlider": True,
            "loginRequired": False,
            "authenticatedPage": False,
            "href": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish",
            "title": "验证码拦截",
            "className": "",
            "bodyText": "请按住滑块",
        },
    ]

    def next_summary():
        return summaries.pop(0) if summaries else {
            "hardBlock": True,
            "hasSlider": True,
            "loginRequired": False,
            "authenticatedPage": False,
        }

    solver._page_challenge_summary = next_summary
    solver._poll_until_authenticated = lambda: False

    result = solver._preflight_current_challenge()

    assert result["manual_required"] is False
    assert result["has_slider"] is True
    assert result["connected"] is True
    assert result["already_authenticated"] is False

def test_preflight_keeps_slider_when_login_and_slider_are_both_present() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.connect_tab = lambda: True
    solver._poll_until_authenticated = lambda: (_ for _ in ()).throw(
        AssertionError("login wait should be skipped when a slider is already present")
    )
    solver._page_challenge_summary = lambda: {
        "hardBlock": True,
        "explicitFailure": False,
        "hasSlider": True,
        "loginRequired": True,
        "authenticatedPage": False,
        "href": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/page/login_jump",
        "title": "登录跳转",
        "className": "",
        "bodyText": "请按住滑块",
    }

    result = solver._preflight_current_challenge()

    assert result["manual_required"] is False
    assert result["has_slider"] is True
    assert result["connected"] is True

def test_is_login_url_covers_login_jump() -> None:
    assert captcha_solver.CaptchaSolver._is_login_url(
        "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/page/login_jump?x5step=1"
    )
    assert captcha_solver.CaptchaSolver._is_login_url(
        "https://login.taobao.com/member/login.jhtml"
    )

def test_solver_stops_without_reload_when_login_page_appears_during_attempt(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    reload_calls: list[bool] = []

    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: None
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "explicitFailure": False,
        "hasSlider": False,
        "loginRequired": True,
        "authenticatedPage": False,
        "title": "登录",
        "className": "",
        "bodyText": "请登录后继续",
    }
    solver._reload_page = lambda: reload_calls.append(True)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "manual_required"
    assert reload_calls == []

def test_solver_returns_success_immediately_when_preflight_is_already_authenticated() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._preflight_current_challenge = lambda: {
        "connected": False,
        "manual_required": False,
        "has_slider": False,
        "already_authenticated": True,
    }
    solver._solve_with_userscript = lambda: (_ for _ in ()).throw(
        AssertionError("authenticated page must not invoke userscript solver")
    )

    assert solver.solve() is True

def test_solver_accepts_authenticated_page_when_slider_disappears_during_attempt(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    calls = {"reload": 0}
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: None
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "explicitFailure": False,
        "hasSlider": False,
        "authenticatedPage": True,
        "title": "司法拍卖",
        "className": "",
        "bodyText": "normal auction list",
    }
    solver._reload_page = lambda: calls.__setitem__("reload", calls["reload"] + 1)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is True
    assert calls["reload"] == 0

def test_verify_success_rejects_success_signal_while_challenge_still_present() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._send_cdp = lambda _method, _params=None: {
        "result": {
            "value": {
                "sliderGone": True,
                "challengeGone": False,
                "successDetected": True,
                "hasError": False,
                "noError": True,
            }
        }
    }

    assert solver._verify_success() is False

def test_verify_success_accepts_disappeared_challenge_without_explicit_success_class() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._send_cdp = lambda _method, _params=None: {
        "result": {
            "value": {
                "success": False,
                "successDetected": False,
                "sliderGone": True,
                "challengeGone": True,
                "hasError": False,
                "noError": True,
            }
        }
    }

    assert solver._verify_success() is True

def test_solver_returns_false_when_official_challenge_explicitly_rejects_drag(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    calls = {"connect": 0, "drag": 0, "reload": 0}

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

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
    solver._verify_success = lambda: False
    solver._reload_page = lambda: calls.__setitem__("reload", calls["reload"] + 1)
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "hasSlider": True,
        "explicitFailure": True,
        "title": "验证码拦截",
        "className": "",
        "bodyText": "验证失败，点击框体重试(error:KzCFR9)",
    }
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve() is False
    assert calls == {"connect": 1, "drag": 1, "reload": 0}

def test_challenge_failure_diagnostic_keeps_error_code_and_removes_url_query() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    diagnostic = solver._challenge_failure_diagnostic(
        {
            "errorCode": "error:TJiA4d/Vx6urd",
            "title": "  Captcha   intercept ",
            "className": "baxia punish",
            "href": "https://sf.taobao.com/list/1.htm?x5secdata=secret&token=secret",
            "bodyText": "must not be logged",
        }
    )

    assert "code=error:TJiA4d/Vx6urd" in diagnostic
    assert "title=Captcha intercept" in diagnostic
    assert "path=https://sf.taobao.com/list/1.htm" in diagnostic
    assert "x5secdata" not in diagnostic
    assert "secret" not in diagnostic
    assert "must not be logged" not in diagnostic

def test_solver_retries_drag_after_nc_asks_to_click_the_bar(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    calls = {"connect": 0, "drag": 0, "reset": 0, "verify": 0}
    verify_results = [False, True]

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag = lambda _x, _y, _d: calls.__setitem__("drag", calls["drag"] + 1) or _d
    solver._wait_for_verification_success = lambda: (
        calls.__setitem__("verify", calls["verify"] + 1) or verify_results.pop(0)
    )
    solver._reset_failed_nc_challenge = lambda: calls.__setitem__("reset", calls["reset"] + 1) or True
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "explicitFailure": True,
        "hasSlider": True,
    }
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=2) is True
    assert calls == {"connect": 2, "drag": 2, "reset": 1, "verify": 2}
    assert solver.last_failure_reason is None

def test_solver_retries_drag_after_nc_retry_without_spending_main_attempt(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    calls = {"connect": 0, "drag": 0, "reset": 0, "verify": 0}
    verify_results = [False, True]

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag = lambda _x, _y, _d: calls.__setitem__("drag", calls["drag"] + 1) or _d
    solver._wait_for_verification_success = lambda: (
        calls.__setitem__("verify", calls["verify"] + 1) or verify_results.pop(0)
    )
    solver._reset_failed_nc_challenge = lambda: calls.__setitem__("reset", calls["reset"] + 1) or True
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "explicitFailure": True,
        "hasSlider": True,
    }
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is True
    assert calls == {"connect": 2, "drag": 2, "reset": 1, "verify": 2}
    assert solver.last_failure_reason is None

def test_solver_can_disable_nc_replay_for_externally_scheduled_attempt(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    calls = {"connect": 0, "drag": 0, "reset": 0, "verify": 0}

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag = lambda _x, _y, _d: calls.__setitem__("drag", calls["drag"] + 1) or _d
    solver._wait_for_verification_success = lambda: calls.__setitem__("verify", calls["verify"] + 1) or False
    solver._reset_failed_nc_challenge = lambda: calls.__setitem__("reset", calls["reset"] + 1) or True
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "explicitFailure": True,
        "hasSlider": True,
    }
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0) is False
    assert calls == {"connect": 1, "drag": 1, "reset": 0, "verify": 1}
    assert solver.last_failure_reason == "manual_required"

def test_solver_can_limit_slider_lookup_for_externally_scheduled_attempt(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    find_calls: list[tuple[int, int]] = []

    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda *, max_retries, retry_delay: (
        find_calls.append((max_retries, retry_delay)) or None
    )
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "hardBlock": False,
        "loginRequired": False,
    }
    solver._reload_page = lambda: None
    solver._recover_authenticated_list_page = lambda: False
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(
        max_attempts=1,
        nc_retry_replay_limit=0,
        slider_find_max_retries=1,
    ) is False
    assert find_calls == [(1, 0)]

def test_solver_switches_profile_without_reset_when_slider_still_present(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223, target_url="https://sf.taobao.com/list/1.htm")
    calls = {"connect": 0, "drag": 0, "reset": 0, "verify": 0}
    profile_indices: list[int] = []
    verify_results = [False, True]

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._find_slider = lambda: {
        "x": 100, "y": 100, "width": 40, "height": 40,
        "selector": "#nc_1_n1z", "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._os_mouse_enabled = lambda: True
    def fake_drag(_x, _y, _d, **kwargs):
        calls["drag"] += 1
        profile_indices.append(kwargs.get("profile_variant_index"))
        return 1

    solver._do_drag_os = fake_drag
    solver._wait_for_verification_success = lambda: (
        calls.__setitem__("verify", calls["verify"] + 1) or verify_results.pop(0)
    )
    solver._reset_failed_nc_challenge = lambda: calls.__setitem__("reset", calls["reset"] + 1) or True
    summaries = [
        {"authenticatedPage": False, "explicitFailure": False, "hasSlider": True},
        {"authenticatedPage": True, "explicitFailure": False, "hasSlider": False},
    ]
    solver._page_challenge_summary = lambda: summaries.pop(0)
    solver._close_owned_target_tabs = lambda: None
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1, drag_profile_offset=1) is True
    assert calls == {"connect": 1, "drag": 2, "reset": 0, "verify": 2}
    assert profile_indices == [1, 2]
    assert solver.last_failure_reason is None
