import json
import time

import requests
import websocket

from src import captcha_solver


def test_connect_tab_reuses_existing_punish_target_before_opening_new_page() -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    )
    connected: list[str] = []
    solver._get_json = lambda _endpoint: [
        {
            "id": "punish-target",
            "url": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?x5step=1",
            "title": "验证码拦截",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/punish-target",
        }
    ]
    solver._open_target_tab = lambda: (_ for _ in ()).throw(
        AssertionError("existing punish target should be reused")
    )
    solver._connect_to_target = lambda target_ws, _title: connected.append(target_ws) or True

    assert solver.connect_tab() is True
    assert connected == ["ws://127.0.0.1:9223/devtools/page/punish-target"]

def test_connect_tab_reuses_existing_login_target_and_bootstraps_websocket(monkeypatch) -> None:
    sent_methods: list[str] = []
    connected_urls: list[str] = []

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            message = json.loads(payload)
            self.last_message_id = int(message["id"])
            sent_methods.append(str(message["method"]))

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

        def close(self) -> None:
            return None

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    )
    solver._get_json = lambda _endpoint: [
        {
            "id": "login-target",
            "url": "https://login.taobao.com/havanaone/login/login.htm",
            "title": "登录",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/login-target",
        }
    ]
    solver._open_target_tab = lambda: (_ for _ in ()).throw(
        AssertionError("existing login target should be reused")
    )
    monkeypatch.setattr(
        websocket,
        "create_connection",
        lambda ws_url, **_kwargs: connected_urls.append(ws_url) or FakeWebSocket(),
    )

    assert solver.connect_tab() is True
    assert connected_urls == ["ws://localhost:9223/devtools/page/login-target"]
    assert "DOM.enable" not in sent_methods
    assert "Runtime.enable" not in sent_methods
    assert "Page.enable" not in sent_methods
    assert "Page.addScriptToEvaluateOnNewDocument" in sent_methods
    assert "Runtime.evaluate" in sent_methods
    assert solver.last_failure_reason is None

def test_manual_challenge_reuse_is_scoped_to_list_or_detail() -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=(
            "https://sf.taobao.com/list/50025969__2.htm"
            "?auction_start_seg=-1&location_code=110114&page=4&st_param=5"
        ),
    )

    assert solver._manual_challenge_matches_requested_target(
        "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5step=1"
    ) is True
    assert solver._manual_challenge_matches_requested_target(
        "https://sf.taobao.com//list/50025970__2.htm/_____tmd_____/punish?x5step=1"
    ) is True
    detail_solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://sf-item.taobao.com/sf_item/601294677898.htm",
    )
    assert detail_solver._manual_challenge_matches_requested_target(
        "https://sf.taobao.com//list/50025970__2.htm/_____tmd_____/punish?x5step=1"
    ) is False
    assert solver._solver_target_route(
        "https://sf-item.taobao.com/sf_item/601294677898.htm?source=a"
    ) != solver._solver_target_route(
        "https://sf-item.taobao.com/sf_item/601294677898.htm?source=b"
    )
    assert solver._solver_target_route(
        "https://sf-item.taobao.com/sf_item/601294677898.htm?track_id=opaque"
    ) == solver._solver_target_route(
        "https://sf-item.taobao.com//sf_item/601294677898.htm/_____tmd_____/punish?x5step=1"
    )

def test_destination_recovery_normalizes_duplicate_path_slashes() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    hrefs = iter(
        (
            "https://sf-item.taobao.com//sf_item/570192626894.htm/_____tmd_____/punish?x5step=1",
            "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5step=1",
        )
    )
    solver._send_cdp = lambda *_args, **_kwargs: {"result": {"value": next(hrefs)}}

    assert solver._destination_list_url() == "https://sf-item.taobao.com/sf_item/570192626894.htm"
    assert solver._destination_list_url() == "https://sf.taobao.com/list/50025969__2.htm"

def test_solver_preserves_owned_challenge_tab_for_manual_verification() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.target_id = "manual-target"
    solver._opened_target_ids.add("manual-target")
    solver._preflight_current_challenge = lambda: {
        "connected": False,
        "manual_required": True,
        "has_slider": False,
        "already_authenticated": False,
    }
    closed: list[str] = []
    solver._close_cdp_target = lambda target_id: closed.append(target_id) or True

    assert solver.solve() is False
    assert closed == []

def test_get_json_retries_transient_timeout_before_success(monkeypatch) -> None:
    attempts: list[int] = []

    class FakeResponse:
        def json(self) -> list[dict[str, str]]:
            return [{"type": "page"}]

    def fake_get(url: str, timeout: int) -> FakeResponse:
        assert url == "http://host.docker.internal:9223/json/list"
        attempts.append(timeout)
        if len(attempts) < 3:
            raise RuntimeError("temporary timeout")
        return FakeResponse()

    monkeypatch.setattr(requests, "get", fake_get)

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    assert solver._get_json("list") == [{"type": "page"}]
    assert attempts == [2, 4, 6]

def test_connect_tab_suppresses_websocket_origin_for_remote_debugging(monkeypatch) -> None:
    connection_kwargs: list[dict[str, object]] = []

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://192.168.65.254:9223",
    )
    solver._get_json = lambda _endpoint: [
        {
            "url": target_url,
            "title": "target solver page",
            "webSocketDebuggerUrl": "ws://192.168.65.254:9223/devtools/page/abc",
        },
    ]

    def fake_create_connection(_ws_url: str, **kwargs: object) -> FakeWebSocket:
        connection_kwargs.append(kwargs)
        return FakeWebSocket()

    monkeypatch.setattr(websocket, "create_connection", fake_create_connection)

    assert solver.connect_tab() is True
    assert connection_kwargs == [{"suppress_origin": True, "timeout": 5}]

def test_send_cdp_mouse_event_consumes_matching_response() -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent_payloads: list[dict[str, object]] = []
            self.recv_count = 0
            self.last_message_id = 0

        def send(self, payload: str) -> None:
            message = json.loads(payload)
            self.sent_payloads.append(message)
            self.last_message_id = int(message["id"])

        def recv(self) -> str:
            self.recv_count += 1
            return json.dumps({"id": self.last_message_id, "result": {}})

    ws = FakeWebSocket()
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.ws = ws

    result = solver._send_cdp(
        "Input.dispatchMouseEvent",
        {"type": "mouseMoved", "x": 10, "y": 20, "button": "none"},
    )

    assert result == {}
    assert len(ws.sent_payloads) == 1
    assert ws.sent_payloads[0]["method"] == "Input.dispatchMouseEvent"
    assert ws.recv_count == 1

def test_solver_falls_back_to_manual_when_cdp_mouse_input_times_out(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    cdp_calls: list[str] = []
    reload_calls: list[bool] = []

    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
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

    def fail_mouse_input(method: str, _params: dict[str, object]) -> None:
        cdp_calls.append(method)
        return None

    solver._send_cdp = fail_mouse_input
    solver._wait_for_verification_success = lambda: (_ for _ in ()).throw(
        AssertionError("verification must not run after CDP mouse input fails")
    )
    solver._reload_page = lambda: reload_calls.append(True)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "manual_required"
    assert [method for method in cdp_calls if method.startswith("Input.")] == [
        "Input.dispatchMouseEvent"
    ]
    assert reload_calls == []

def test_solver_returns_false_quickly_for_baxia_hard_block(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    calls = {"connect": 0, "reload": 0, "sleep": []}

    def fake_connect() -> bool:
        calls["connect"] += 1
        return True

    solver.connect_tab = fake_connect
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: None
    solver._reload_page = lambda: calls.__setitem__("reload", calls["reload"] + 1)
    solver._page_challenge_summary = lambda: {
        "hardBlock": True,
        "hasSlider": False,
        "title": "captcha intercept",
        "className": "baxia-punish denyfromx5 pc",
        "bodyText": "blocked by baxia",
    }

    def fake_sleep(seconds: float) -> None:
        calls["sleep"].append(seconds)
        raise AssertionError("solver should not retry/sleep on an unsupported hard block")

    monkeypatch.setattr(time, "sleep", fake_sleep)

    assert solver.solve() is False
    assert calls["connect"] == 1
    assert calls["reload"] == 0

def test_solver_skips_headed_playwright_branches_without_display(monkeypatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("FAPAI_SOLVER_ENABLE_HEADED_PLAYWRIGHT", raising=False)
    solver = captcha_solver.CaptchaSolver(port=9223)
    calls: list[str] = []

    solver._preflight_current_challenge = lambda: {
        "connected": False,
        "manual_required": False,
        "has_slider": False,
    }
    solver._solve_with_ddddocr = lambda: calls.append("ddddocr") or False
    solver._solve_with_playwright_stealth = lambda: calls.append("playwright_stealth") or False
    solver._solve_with_userscript = lambda: calls.append("userscript") or True
    solver.connect_tab = lambda: calls.append("cdp") or False
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1) is False
    assert "ddddocr" not in calls
    assert "playwright_stealth" not in calls
    assert "userscript" not in calls
    assert calls == ["cdp"]

def test_headed_playwright_fallback_requires_explicit_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.delenv("FAPAI_SOLVER_ENABLE_HEADED_PLAYWRIGHT", raising=False)
    solver = captcha_solver.CaptchaSolver(port=9223)

    assert solver._headed_playwright_enabled() is False

    monkeypatch.setenv("FAPAI_SOLVER_ENABLE_HEADED_PLAYWRIGHT", "1")

    assert solver._headed_playwright_enabled() is True

def test_preflight_marks_normal_auction_page_as_already_authenticated() -> None:
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
        "authenticatedPage": True,
        "title": "司法拍卖",
        "className": "",
        "bodyText": "normal auction list",
    }

    result = solver._preflight_current_challenge()

    assert result["already_authenticated"] is True
    assert result["connected"] is False
    assert ws.closed is True
    assert solver.ws is None

def test_preflight_accepts_valid_auction_payload_with_generic_hidden_challenge_copy() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.connect_tab = lambda: True
    solver._page_challenge_summary = lambda: {
        "hardBlock": False,
        "explicitFailure": False,
        "hasSlider": False,
        "challengePresent": False,
        "challengeMarker": True,
        "validAuctionPayload": True,
        "authenticatedPage": True,
        "title": "司法拍卖",
        "bodyText": "auction list payload",
    }

    result = solver._preflight_current_challenge()

    assert result["already_authenticated"] is True
    assert result["manual_required"] is False

def test_preflight_marks_login_page_as_manual_required() -> None:
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
        "loginRequired": True,
        "authenticatedPage": False,
        "title": "登录",
        "className": "",
        "bodyText": "请登录后继续",
    }

    result = solver._preflight_current_challenge()

    assert result["manual_required"] is True
    assert result["connected"] is False
    assert ws.closed is True
    assert solver.ws is None
    assert solver.last_failure_reason == "manual_required"

def test_preflight_treats_login_jump_as_login_required() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.connect_tab = lambda: True
    solver._page_challenge_summary = lambda: {
        "hardBlock": True,
        "explicitFailure": False,
        "hasSlider": False,
        "loginRequired": True,
        "authenticatedPage": False,
        "href": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/page/login_jump?x5step=1",
        "title": "登录跳转",
        "className": "",
        "bodyText": "",
    }

    result = solver._preflight_current_challenge()

    assert result["manual_required"] is True
    assert result["already_authenticated"] is False
    assert result["has_slider"] is False
    assert solver.last_failure_reason == "manual_required"
