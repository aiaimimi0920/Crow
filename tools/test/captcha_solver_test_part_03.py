import json
import time

import websocket

from src import captcha_solver


def test_connect_tab_keeps_other_collection_scope_challenge_open() -> None:
    target_url = "https://sf-item.taobao.com/sf_item/570192626894.htm?__captcha_solver_bg=1"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
    tabs = [
        {
            "id": "detail-slider",
            "type": "page",
            "url": "https://sf-item.taobao.com/sf_item/111.htm/_____tmd_____/punish?x5secdata=a",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/detail-slider",
        },
        {
            "id": "detail-duplicate",
            "type": "page",
            "url": "https://sf-item.taobao.com/sf_item/222.htm/_____tmd_____/punish?x5secdata=b",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/detail-duplicate",
        },
        {
            "id": "seed-slider",
            "type": "page",
            "url": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?x5secdata=c",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/seed-slider",
        },
    ]
    solver._get_json = lambda _endpoint: tabs
    closed: list[str] = []
    connected: list[str] = []
    solver._close_cdp_target = lambda target_id: closed.append(target_id) or True
    solver._connect_to_target = lambda target_ws, _title: connected.append(target_ws) or True

    assert solver.connect_tab() is True
    assert closed == ["detail-duplicate"]
    assert connected == ["ws://127.0.0.1:9223/devtools/page/detail-slider"]

def test_connect_tab_prefers_exact_detail_route_over_cached_scope_target() -> None:
    target_url = "https://sf-item.taobao.com/sf_item/783241065461.htm?__captcha_solver_bg=1"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
    solver.target_id = "stale-detail"
    stale = {
        "id": "stale-detail",
        "type": "page",
        "title": "CAPTCHA Verification",
        "url": "https://sf-item.taobao.com/sf_item/798660177183.htm/_____tmd_____/punish",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/stale-detail",
    }
    requested = {
        "id": "requested-detail",
        "type": "page",
        "title": "CAPTCHA Verification",
        "url": "https://sf-item.taobao.com/sf_item/783241065461.htm/_____tmd_____/punish",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/requested-detail",
    }
    seed = {
        "id": "seed-challenge",
        "type": "page",
        "title": "CAPTCHA Verification",
        "url": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/seed-challenge",
    }
    list_calls = 0

    def fake_get_json(_endpoint):
        nonlocal list_calls
        list_calls += 1
        return [stale, requested, seed] if list_calls == 1 else [requested, seed]

    closed: list[str] = []
    connected: list[str] = []
    solver._get_json = fake_get_json
    solver._close_cdp_target = lambda target_id: closed.append(target_id) or True
    solver._connect_to_target = lambda target_ws, _title: connected.append(target_ws) or True

    assert solver.connect_tab() is True
    assert closed == ["stale-detail"]
    assert connected == ["ws://127.0.0.1:9223/devtools/page/requested-detail"]

def test_connect_tab_prunes_title_only_challenge_duplicates_and_refreshes_tabs() -> None:
    target_url = "https://sf.taobao.com/list/50025969__2.htm?page=7&__captcha_solver_bg=1"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
    duplicate = {
        "id": "seed-duplicate",
        "type": "page",
        "title": "CAPTCHA Verification",
        "url": "https://sf.taobao.com/list/50025969__2.htm?page=7&st_param=5",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/seed-duplicate",
    }
    kept = {
        "id": "seed-kept",
        "type": "page",
        "title": "CAPTCHA Verification",
        "url": "https://sf.taobao.com/list/50025969__2.htm?page=7&st_param=1",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/seed-kept",
    }
    detail = {
        "id": "detail-challenge",
        "type": "page",
        "title": "CAPTCHA Verification",
        "url": "https://sf-item.taobao.com/sf_item/123.htm",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/detail-challenge",
    }
    normal = {
        "id": "normal-seed",
        "type": "page",
        "title": "司法拍卖",
        "url": "https://sf.taobao.com/list/50025969__2.htm?page=8",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/normal-seed",
    }
    list_calls = 0

    def fake_get_json(_endpoint):
        nonlocal list_calls
        list_calls += 1
        return [kept, duplicate, detail, normal] if list_calls == 1 else [kept, detail, normal]

    closed: list[str] = []
    connected: list[str] = []
    solver._get_json = fake_get_json
    solver._close_cdp_target = lambda target_id: closed.append(target_id) or True
    solver._connect_to_target = lambda target_ws, _title: connected.append(target_ws) or True

    assert solver.connect_tab() is True
    assert closed == ["seed-duplicate"]
    assert list_calls >= 2
    assert connected == ["ws://127.0.0.1:9223/devtools/page/seed-kept"]

def test_nc_error_widget_contract_recognizes_english_refresh_failure() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    expressions: list[str] = []

    def fake_send(_method, params):
        expressions.append(str(params.get("expression") or ""))
        return {"result": {"value": {"explicitFailure": True, "hasSlider": False}}}

    solver._send_cdp = fake_send

    assert solver._page_challenge_summary()["explicitFailure"] is True
    assert "please refresh page and try again" in expressions[0]
    assert ".errloading" in expressions[0]
    assert "var hasSlider = hasVisibleMatch(doc," in expressions[0]

    expressions.clear()
    solver._nc_retry_targets()
    assert ".errloading" in expressions[0]
    assert "please refresh page and try again" in expressions[0]

def test_slider_miss_clears_closed_websocket_before_recovery(monkeypatch) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    solver = captcha_solver.CaptchaSolver(port=9223)
    socket = FakeWebSocket()
    solver.ws = socket
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda **_kwargs: None
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "hardBlock": False,
        "hasSlider": False,
        "loginRequired": False,
    }
    solver._reload_page = lambda: None
    recovery_websockets: list[object | None] = []

    def fake_recover() -> bool:
        recovery_websockets.append(solver.ws)
        return False

    solver._recover_authenticated_list_page = fake_recover
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0, slider_find_max_retries=1) is False
    assert socket.closed is True
    assert recovery_websockets == [None]

def test_verification_failure_recovers_before_closing_websocket(monkeypatch) -> None:
    class FakeWebSocket:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    solver = captcha_solver.CaptchaSolver(port=9223)
    socket = FakeWebSocket()
    solver.ws = socket
    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda **_kwargs: {
        "x": 100,
        "y": 100,
        "width": 40,
        "height": 40,
        "selector": "#nc_1_n1z",
        "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._get_track_rect = lambda: None
    solver._do_drag = lambda *_args, **_kwargs: 260
    solver._wait_for_verification_success = lambda: False
    solver._page_challenge_summary = lambda: {
        "authenticatedPage": False,
        "hasSlider": False,
        "explicitFailure": False,
    }
    solver._reload_page = lambda: None
    recovery_websockets: list[object | None] = []

    def fake_recover() -> bool:
        recovery_websockets.append(solver.ws)
        return False

    solver._recover_authenticated_list_page = fake_recover
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1, nc_retry_replay_limit=0, slider_find_max_retries=1) is False
    assert recovery_websockets == [socket]
    assert socket.closed is True
    assert solver.ws is None

def test_connect_tab_falls_back_when_cached_websocket_cdp_bootstrap_times_out(monkeypatch) -> None:
    connected_urls: list[str] = []
    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"

    class StaleWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            raise websocket.WebSocketTimeoutException("stale target")

        def close(self) -> None:
            return None

    class HealthyWebSocket:
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

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://host.docker.internal:9223",
    )
    solver.target_ws_url = "ws://host.docker.internal:9223/devtools/page/stale-cached"
    solver._get_json = lambda _endpoint: [
        {
            "id": "target-1",
            "url": target_url,
            "title": "fresh solver target",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/target-1",
        },
    ]

    stale = StaleWebSocket()
    healthy = HealthyWebSocket()

    def fake_create_connection(ws_url: str, **_kwargs: bool):
        connected_urls.append(ws_url)
        if ws_url.endswith("/stale-cached"):
            return stale
        return healthy

    monkeypatch.setattr(websocket, "create_connection", fake_create_connection)

    assert solver.connect_tab() is True
    assert connected_urls == [
        "ws://host.docker.internal:9223/devtools/page/stale-cached",
        "ws://host.docker.internal:9223/devtools/page/target-1",
    ]
    assert solver.target_ws_url == "ws://host.docker.internal:9223/devtools/page/target-1"

def test_punish_target_connection_failure_marks_cdp_unavailable(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._remember_target_tab(
        {
            "id": "punish-target",
            "url": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?x5step=1",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/punish-target",
        }
    )
    monkeypatch.setattr(
        websocket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cdp bootstrap unavailable")),
    )

    assert solver._connect_to_target(solver.target_ws_url, "验证码拦截") is False
    assert solver.last_failure_reason == "cdp_unavailable"

def test_target_websocket_connection_has_a_bounded_bootstrap_timeout(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    connection_kwargs: dict[str, object] = {}

    class FakeWebSocket:
        def __init__(self) -> None:
            self.timeout: float | None = None

        def settimeout(self, timeout: float) -> None:
            self.timeout = timeout

        def close(self) -> None:
            return None

    fake_websocket = FakeWebSocket()

    def fake_create_connection(_target_ws: str, **kwargs: object) -> FakeWebSocket:
        connection_kwargs.update(kwargs)
        return fake_websocket

    monkeypatch.setenv("FAPAI_SOLVER_DISABLE_STEALTH", "1")
    monkeypatch.setattr(websocket, "create_connection", fake_create_connection)
    monkeypatch.setattr(solver, "_send_cdp", lambda *_args, **_kwargs: {})

    assert solver._connect_to_target("ws://127.0.0.1:9223/devtools/page/test", "test") is True
    assert connection_kwargs == {"suppress_origin": True, "timeout": 5}
    assert fake_websocket.timeout == 5

def test_target_connection_applies_windows_identity_to_the_current_challenge(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    sent: list[tuple[str, dict[str, object]]] = []

    class FakeWebSocket:
        timeout = None

        def settimeout(self, value: float) -> None:
            self.timeout = value

        def close(self) -> None:
            return None

    monkeypatch.setenv(
        "FAPAI_BROWSER_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36",
    )
    monkeypatch.setenv("FAPAI_BROWSER_IDENTITY_FULL_VERSION", "151.0.7922.174")
    monkeypatch.setattr(
        websocket,
        "create_connection",
        lambda *_args, **_kwargs: FakeWebSocket(),
    )

    def fake_send(method: str, params: dict[str, object] | None = None):
        sent.append((method, params or {}))
        return {}

    monkeypatch.setattr(solver, "_send_cdp", fake_send)

    assert solver._connect_to_target(
        "ws://127.0.0.1:9223/devtools/page/test",
        "CAPTCHA Verification",
    ) is True

    methods = [method for method, _params in sent]
    assert methods.index("Emulation.setUserAgentOverride") < methods.index(
        "Page.addScriptToEvaluateOnNewDocument"
    )
    identity = next(params for method, params in sent if method == "Emulation.setUserAgentOverride")
    assert identity["platform"] == "Win32"
    assert identity["userAgentMetadata"]["platform"] == "Windows"
    stealth = next(
        params["source"]
        for method, params in sent
        if method == "Page.addScriptToEvaluateOnNewDocument"
    )
    assert "'platform', 'Win32'" in stealth
    assert "'language', 'zh-CN'" in stealth
    assert "'webdriver', false" in stealth
    assert "'languages', ['zh-CN', 'zh']" in stealth
    assert ("Emulation.setTimezoneOverride", {"timezoneId": "Asia/Shanghai"}) in sent
    assert ("Emulation.setLocaleOverride", {"locale": "zh-CN"}) in sent

def test_preflight_propagates_manual_required_from_failed_punish_connection() -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)

    def fail_connect() -> bool:
        solver.last_failure_reason = "manual_required"
        return False

    solver.connect_tab = fail_connect

    result = solver._preflight_current_challenge()

    assert result["manual_required"] is True
    assert result["already_authenticated"] is False
