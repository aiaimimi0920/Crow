import json
import time

import requests
import websocket

from src import captcha_solver


def test_compact_cdp_pages_keeps_browser_alive_at_threshold(monkeypatch) -> None:
    requested: list[tuple[str, str, int]] = []
    closed_ws = {"count": 0}

    class FakeResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def json(self) -> object:
            return self._payload

    class FakeWebSocket:
        def close(self) -> None:
            closed_ws["count"] += 1

    page_targets = [
        {"id": f"page-{index}", "type": "page", "url": f"https://sf.taobao.com/list/{index}"}
        for index in range(12)
    ]
    other_targets = [
        {"id": "worker-1", "type": "service_worker", "url": "chrome-extension://worker"},
        {"id": "iframe-1", "type": "iframe", "url": "https://example.local/frame"},
    ]

    def fake_get(url: str, timeout: int):
        requested.append(("GET", url, timeout))
        if url.endswith("/json/list"):
            return FakeResponse(page_targets + other_targets)
        if "/json/close/" in url:
            return FakeResponse({})
        raise AssertionError(f"unexpected GET {url}")

    def fake_put(url: str, timeout: int):
        requested.append(("PUT", url, timeout))
        if url.endswith("/json/new?about:blank"):
            return FakeResponse({"id": "keepalive-page"})
        raise AssertionError(f"unexpected PUT {url}")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "put", fake_put)

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://contest.local/challenge?__captcha_solver_bg=1",
        cdp_endpoint="http://host.docker.internal:9223",
    )
    solver.ws = FakeWebSocket()
    solver.target_id = "page-3"
    solver.target_ws_url = "ws://cached-target"

    summary = solver._compact_cdp_pages_if_needed()

    assert summary == {
        "triggered": True,
        "page_count": 12,
        "closed": 12,
        "keepalive_target_id": "keepalive-page",
    }
    assert closed_ws["count"] == 1
    assert solver.ws is None
    assert solver.target_id is None
    assert solver.target_ws_url is None
    assert ("PUT", "http://host.docker.internal:9223/json/new?about:blank", 5) in requested
    close_urls = [url for method, url, _timeout in requested if method == "GET" and "/json/close/" in url]
    assert close_urls == [
        f"http://host.docker.internal:9223/json/close/page-{index}" for index in range(12)
    ]
    assert "http://host.docker.internal:9223/json/close/worker-1" not in close_urls
    assert "http://host.docker.internal:9223/json/close/iframe-1" not in close_urls

def test_compact_cdp_pages_does_not_close_below_threshold(monkeypatch) -> None:
    requested: list[tuple[str, str, int]] = []

    class FakeResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def json(self) -> object:
            return self._payload

    def fake_get(url: str, timeout: int):
        requested.append(("GET", url, timeout))
        if url.endswith("/json/list"):
            return FakeResponse(
                [{"id": f"page-{index}", "type": "page"} for index in range(11)]
                + [{"id": "worker-1", "type": "service_worker"}]
            )
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(requests, "get", fake_get)

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    assert solver._compact_cdp_pages_if_needed() == {"triggered": False, "page_count": 11, "closed": 0}
    assert all("/json/close/" not in url for _method, url, _timeout in requested)

def test_connect_tab_compacts_accumulated_pages_then_reopens_current_target(monkeypatch) -> None:
    requested: list[tuple[str, str, int]] = []
    connected_urls: list[str] = []
    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"
    current_targets: list[dict[str, str]] = [
        {"id": f"page-{index}", "type": "page", "url": f"https://stale.local/{index}"}
        for index in range(12)
    ]

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
            return FakeResponse(current_targets)
        if "/json/close/" in url:
            target_id = url.rsplit("/", 1)[-1]
            current_targets[:] = [target for target in current_targets if target.get("id") != target_id]
            return FakeResponse({})
        raise AssertionError(f"unexpected GET {url}")

    def fake_put(url: str, timeout: int):
        requested.append(("PUT", url, timeout))
        return FakeResponse(
            {
                "id": "fresh-current-task",
                "type": "page",
                "url": target_url,
                "title": "target solver page",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/fresh-current-task",
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
    assert len([url for _method, url, _timeout in requested if "/json/close/page-" in url]) == 12
    assert (
        "PUT",
        "http://host.docker.internal:9223/json/new?https://contest.local/challenge%3F__captcha_solver_bg%3D1",
        5,
    ) in requested
    assert solver.target_id == "fresh-current-task"
    assert connected_urls == ["ws://host.docker.internal:9223/devtools/page/fresh-current-task"]

def test_connect_tab_reserves_space_before_opening_twelfth_page(monkeypatch) -> None:
    requested: list[tuple[str, str, int]] = []
    target_url = "https://contest.local/challenge?__captcha_solver_bg=1"
    current_targets: list[dict[str, str]] = [
        {"id": f"page-{index}", "type": "page", "url": f"https://stale.local/{index}"}
        for index in range(11)
    ]

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
            return FakeResponse(current_targets)
        if "/json/close/" in url:
            target_id = url.rsplit("/", 1)[-1]
            current_targets[:] = [target for target in current_targets if target.get("id") != target_id]
            return FakeResponse({})
        raise AssertionError(f"unexpected GET {url}")

    def fake_put(url: str, timeout: int):
        requested.append(("PUT", url, timeout))
        return FakeResponse(
            {
                "id": "fresh-current-task",
                "type": "page",
                "url": target_url,
                "title": "target solver page",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/fresh-current-task",
            }
        )

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "put", fake_put)
    monkeypatch.setattr(
        websocket,
        "create_connection",
        lambda _ws_url, **_kwargs: FakeWebSocket(),
    )

    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url=target_url,
        cdp_endpoint="http://host.docker.internal:9223",
    )

    assert solver.connect_tab() is True
    assert len([url for _method, url, _timeout in requested if "/json/close/page-" in url]) == 11
    assert any(method == "PUT" and "/json/new?" in url for method, url, _timeout in requested)

def test_solver_closes_owned_target_tab_after_cdp_success(monkeypatch) -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://contest.local/challenge?__captcha_solver_bg=1",
        cdp_endpoint="http://host.docker.internal:9223",
    )
    solver.target_id = "owned-target"
    solver._opened_target_ids.add("owned-target")
    closed: list[str] = []

    solver._preflight_current_challenge = lambda: {
        "connected": True,
        "manual_required": False,
        "has_slider": True,
        "already_authenticated": False,
    }
    solver._headed_playwright_enabled = lambda: False
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
    solver._do_drag = lambda _x, _y, _distance: 250
    solver._wait_for_verification_success = lambda: True
    solver._close_cdp_target = lambda target_id: closed.append(target_id) or True
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve() is True
    assert closed == ["owned-target"]
    assert solver.target_id is None
    assert solver.target_ws_url is None

def test_connect_tab_reuses_cached_target_websocket_when_list_is_unavailable(monkeypatch) -> None:
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

    list_calls = {"count": 0}

    def fake_get(url: str, timeout: int):
        requested.append(("GET", url, timeout))
        if url.endswith("/json/list"):
            list_calls["count"] += 1
            if list_calls["count"] == 1:
                return FakeResponse(
                    [
                        {
                            "url": "https://sf.taobao.com/",
                            "title": "home",
                            "webSocketDebuggerUrl": "ws://home",
                        }
                    ]
                )
            raise RuntimeError("cdp list timed out")
        raise AssertionError(f"unexpected GET {url}")

    def fake_put(url: str, timeout: int):
        requested.append(("PUT", url, timeout))
        return FakeResponse(
            {
                "id": "target-1",
                "url": target_url,
                "title": "target solver page",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/target-1",
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
    assert solver.connect_tab() is True
    assert connected_urls == [
        "ws://host.docker.internal:9223/devtools/page/target-1",
        "ws://host.docker.internal:9223/devtools/page/target-1",
    ]
    assert len([item for item in requested if item[0] == "PUT"]) == 1

def test_connect_tab_reuses_probed_target_before_page_compaction() -> None:
    solver = captcha_solver.CaptchaSolver(
        port=9223,
        target_url="https://sf.taobao.com/list/50025969__2.htm?page=3&__captcha_solver_bg=1",
    )
    solver._remember_target_tab(
        {
            "id": "visible-slider",
            "url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/visible-slider",
        }
    )
    solver._get_json = lambda _endpoint: [
        {
            "id": f"page-{index}",
            "type": "page",
            "url": f"https://example.test/{index}",
            "webSocketDebuggerUrl": f"ws://127.0.0.1:9223/devtools/page/page-{index}",
        }
        for index in range(captcha_solver.DEFAULT_CDP_PAGE_TARGET_LIMIT)
    ]
    solver._compact_cdp_pages_if_needed = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("a live probed target must be reused before compaction")
    )
    connected: list[str] = []
    solver._connect_to_target = lambda target_ws, _title: connected.append(target_ws) or True

    assert solver.connect_tab() is True
    assert connected == ["ws://127.0.0.1:9223/devtools/page/visible-slider"]

def test_connect_tab_prunes_same_route_duplicates_before_cached_target_reuse() -> None:
    target_url = "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"
    solver = captcha_solver.CaptchaSolver(port=9223, target_url=target_url)
    solver._remember_target_tab(
        {
            "id": "visible-slider",
            "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5secdata=a",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/visible-slider",
        }
    )
    tabs = [
        {
            "id": "visible-slider",
            "type": "page",
            "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5secdata=a",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/visible-slider",
        },
        {
            "id": "duplicate-slider",
            "type": "page",
            "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5secdata=b",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/duplicate-slider",
        },
    ]
    solver._get_json = lambda _endpoint: tabs
    closed: list[str] = []
    connected: list[str] = []
    solver._close_cdp_target = lambda target_id: closed.append(target_id) or True
    solver._connect_to_target = lambda target_ws, _title: connected.append(target_ws) or True

    assert solver.connect_tab() is True
    assert closed == ["duplicate-slider"]
    assert connected == ["ws://127.0.0.1:9223/devtools/page/visible-slider"]
