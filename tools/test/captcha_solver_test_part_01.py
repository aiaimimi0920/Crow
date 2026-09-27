import json
import time

import requests
import websocket

from src import captcha_solver


def test_bring_to_front_skips_slow_websocket_focus_after_exact_activation(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(cdp_endpoint="http://127.0.0.1:9223")
    solver.target_id = "challenge-target"
    calls: list[tuple[str, object]] = []

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(
        requests,
        "get",
        lambda url, timeout: calls.append(("http", (url, timeout))) or FakeResponse(),
    )
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda method, params=None: calls.append(("cdp", method)) or None,
    )
    monkeypatch.setattr(time, "sleep", lambda seconds: calls.append(("sleep", seconds)))

    assert solver._bring_to_front() is True
    assert calls[0] == (
        "http",
        ("http://127.0.0.1:9223/json/activate/challenge-target", 2),
    )
    assert calls[1:] == [("sleep", 0.15)]

def test_bring_to_front_falls_back_to_websocket_focus_when_http_activation_fails(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(cdp_endpoint="http://127.0.0.1:9223")
    solver.target_id = "challenge-target"
    calls: list[str] = []

    class FakeResponse:
        status_code = 500

    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: FakeResponse())
    monkeypatch.setattr(
        solver,
        "_send_cdp",
        lambda method, params=None: calls.append(method) or {"ok": True},
    )
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver._bring_to_front() is True
    assert calls == ["Page.bringToFront", "Runtime.evaluate"]

def test_find_slider_stops_immediately_when_cancel_requested(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver.cancel_checker = lambda: True
    cdp_calls: list[tuple[str, dict[str, object]]] = []
    sleeps: list[float] = []

    def fake_send_cdp(method: str, params: dict[str, object]) -> dict[str, object]:
        cdp_calls.append((method, params))
        return {}

    monkeypatch.setattr(solver, "_send_cdp", fake_send_cdp)
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))

    assert solver._find_slider() is None
    assert solver.last_failure_reason == "cancelled"
    assert cdp_calls == []
    assert sleeps == []

def test_connect_tab_prioritizes_request_target_url(monkeypatch) -> None:
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

    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
    solver._get_json = lambda _endpoint: [
        {
            "url": "https://other.local/challenge?__captcha_solver_bg=1",
            "title": "other solver page",
            "webSocketDebuggerUrl": "ws://other",
        },
        {
            "url": target_url,
            "title": "target solver page",
            "webSocketDebuggerUrl": "ws://target",
        },
    ]

    monkeypatch.setattr(
        websocket,
        "create_connection",
        lambda ws_url, **_kwargs: connected_urls.append(ws_url) or FakeWebSocket(),
    )

    assert solver.connect_tab() is True
    assert connected_urls == ["ws://target"]
    assert "DOM.enable" not in sent_methods
    assert "Runtime.enable" not in sent_methods
    assert "Page.enable" not in sent_methods
    assert "Page.addScriptToEvaluateOnNewDocument" in sent_methods
    assert "Runtime.evaluate" in sent_methods

def test_connect_tab_matches_requested_target_url_after_query_normalization(monkeypatch) -> None:
    connected_urls: list[str] = []

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

    target_url = "file:///tmp/mock_slider.html?b=2&a=1&verifyMode=near_miss"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
    solver._get_json = lambda _endpoint: [
        {
            "url": "file:///tmp/mock_slider.html?verifyMode=near_miss&a=1&b=2",
            "title": "target solver page",
            "webSocketDebuggerUrl": "ws://target",
        },
    ]

    monkeypatch.setattr(
        websocket,
        "create_connection",
        lambda ws_url, **_kwargs: connected_urls.append(ws_url) or FakeWebSocket(),
    )

    assert solver.connect_tab() is True
    assert connected_urls == ["ws://target"]

def test_get_json_uses_configured_cdp_endpoint(monkeypatch) -> None:
    requested_urls: list[str] = []

    class FakeResponse:
        def json(self) -> list[dict[str, str]]:
            return [{"type": "page"}]

    def fake_get(url: str, timeout: int) -> FakeResponse:
        requested_urls.append(url)
        assert timeout == 2
        return FakeResponse()

    monkeypatch.setattr(requests, "get", fake_get)

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    assert solver._get_json("list") == [{"type": "page"}]
    assert requested_urls == ["http://host.docker.internal:9223/json/list"]

def test_constructor_prefers_env_cdp_endpoint_over_legacy_default_port(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://192.168.65.254:9223")

    solver = captcha_solver.CaptchaSolver(port=9222)

    assert solver.port == 9223
    assert solver.cdp_endpoint == "http://192.168.65.254:9223"

def test_connect_tab_rewrites_loopback_websocket_to_configured_cdp_endpoint(monkeypatch) -> None:
    connected_urls: list[str] = []

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
        cdp_endpoint="http://host.docker.internal:9223",
    )
    solver._get_json = lambda _endpoint: [
        {
            "url": target_url,
            "title": "target solver page",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/abc",
        },
    ]

    monkeypatch.setattr(
        websocket,
        "create_connection",
        lambda ws_url, **_kwargs: connected_urls.append(ws_url) or FakeWebSocket(),
    )

    assert solver.connect_tab() is True
    assert connected_urls == ["ws://host.docker.internal:9223/devtools/page/abc"]

def test_connect_tab_opens_requested_target_when_missing(monkeypatch) -> None:
    requested: list[tuple[str, str, int]] = []
    connected_urls: list[str] = []
    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"

    class FakeResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def json(self) -> object:
            return self._payload

    class FakeWebSocket:
        def __init__(self) -> None:
            self.last_message_id = 0

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message_id = int(json.loads(payload)["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.last_message_id, "result": {}})

    def fake_get(url: str, timeout: int):
        requested.append(("GET", url, timeout))
        if url.endswith("/json/list"):
            return FakeResponse(
                [
                    {
                        "url": "https://sf.taobao.com/",
                        "title": "home",
                        "webSocketDebuggerUrl": "ws://home",
                    }
                ]
            )
        raise AssertionError(f"unexpected GET {url}")

    def fake_put(url: str, timeout: int):
        requested.append(("PUT", url, timeout))
        return FakeResponse(
            {
                "url": target_url,
                "title": "target solver page",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/new-target",
            }
        )

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "put", fake_put)
    monkeypatch.setattr(
        websocket,
        "create_connection",
        lambda ws_url, **_kwargs: connected_urls.append(ws_url) or FakeWebSocket(),
    )

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    assert solver.connect_tab() is True
    assert (
        "PUT",
        "http://host.docker.internal:9223/json/new?https://contest.local/challenge%3F__captcha_solver_bg%3D1",
        5,
    ) in requested
    assert connected_urls == ["ws://host.docker.internal:9223/devtools/page/new-target"]

def test_open_target_tab_encodes_nested_query_delimiters(monkeypatch) -> None:
    requested_urls: list[str] = []
    target_url = (
        "file:///tmp/mock_slider.html"
        "?target=local_mock_slider_wide_delay"
        "&trackWidth=520"
        "&handleWidth=34"
        "&handleHeight=34"
        "&successDelayMs=900"
        "&verifyMode=strict_success_text"
    )

    class FakeResponse:
        def json(self) -> dict[str, str]:
            return {"id": "target-1", "url": target_url, "webSocketDebuggerUrl": "ws://target-1"}

    monkeypatch.setattr(
        requests,
        "put",
        lambda url, timeout: requested_urls.append(url) or FakeResponse(),
    )

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    payload = solver._open_target_tab()

    assert payload == {"id": "target-1", "url": target_url, "webSocketDebuggerUrl": "ws://target-1"}
    assert requested_urls == [
        "http://host.docker.internal:9223/json/new?"
        "file:///tmp/mock_slider.html%3FhandleHeight%3D34%26handleWidth%3D34%26successDelayMs%3D900"
        "%26target%3Dlocal_mock_slider_wide_delay%26trackWidth%3D520%26verifyMode%3Dstrict_success_text"
    ]

def test_open_target_tab_collapses_duplicate_http_path_slashes(monkeypatch) -> None:
    requested_urls: list[str] = []
    prepared_urls: list[str] = []

    class FakeResponse:
        def json(self) -> dict[str, str]:
            return {"id": "target-1", "url": "about:blank", "webSocketDebuggerUrl": "ws://target-1"}

    monkeypatch.setattr(
        requests,
        "put",
        lambda url, timeout: requested_urls.append(url) or FakeResponse(),
    )
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://sf-item.taobao.com//sf_item/664322499931.htm?source=test",
        cdp_endpoint="http://host.docker.internal:9223",
    )
    solver._prepare_opened_target_before_navigation = (
        lambda payload, target_url: prepared_urls.append(target_url)
        or payload.__setitem__("url", target_url)
        or True
    )

    assert solver._open_target_tab() == {
        "id": "target-1",
        "url": "https://sf-item.taobao.com/sf_item/664322499931.htm?source=test",
        "webSocketDebuggerUrl": "ws://target-1",
    }
    assert requested_urls == [
        "http://host.docker.internal:9223/json/new?about:blank"
    ]
    assert prepared_urls == [
        "https://sf-item.taobao.com/sf_item/664322499931.htm?source=test"
    ]

def test_taobao_target_installs_identity_before_navigation(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(port=9223)
    connected: list[tuple[str, str]] = []
    commands: list[tuple[str, dict[str, object]]] = []
    solver._connect_to_target = (
        lambda target_ws, title: connected.append((target_ws, title)) or True
    )
    solver._send_cdp = (
        lambda method, params=None: commands.append((method, params or {})) or {}
    )
    payload = {
        "id": "target-1",
        "url": "about:blank",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/target-1",
    }
    target_url = "https://sf-item.taobao.com/sf_item/664322499931.htm"

    assert solver._prepare_opened_target_before_navigation(payload, target_url) is True

    assert connected == [
        ("ws://127.0.0.1:9223/devtools/page/target-1", "new solver target")
    ]
    assert commands == [("Page.navigate", {"url": target_url})]
    assert payload["url"] == target_url
    assert solver.current_target_url == target_url
