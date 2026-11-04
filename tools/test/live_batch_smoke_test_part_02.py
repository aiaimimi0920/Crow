from tools.test.live_batch_smoke_test_context import *  # noqa: F401,F403


def test_connect_browser_over_cdp_uses_extended_timeout(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    compaction_calls: list[str] = []

    class _Chromium:
        @staticmethod
        def connect_over_cdp(endpoint: str, *, timeout: int):
            calls.append((endpoint, timeout))
            return {"endpoint": endpoint}

    class _Playwright:
        chromium = _Chromium()

    def _compact(endpoint: str) -> dict[str, object]:
        compaction_calls.append(endpoint)
        return {"triggered": False}

    monkeypatch.setattr(live_batch_smoke, "compact_cdp_page_targets_if_needed", _compact)
    monkeypatch.setattr(live_batch_smoke, "resolve_playwright_cdp_endpoint", lambda endpoint: endpoint)
    browser = live_batch_smoke.connect_browser_over_cdp(_Playwright(), "http://127.0.0.1:9223")

    assert browser == {"endpoint": "http://127.0.0.1:9223"}
    assert calls == [("http://127.0.0.1:9223", 120000)]
    assert compaction_calls == [], "connecting must never close shared pages"

def test_connect_browser_over_cdp_prefers_browser_websocket_url_for_http_endpoint(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    class _Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {
                "webSocketDebuggerUrl": "ws://192.168.15.104:9224/devtools/browser/browser-1",
            }

    class _Chromium:
        @staticmethod
        def connect_over_cdp(endpoint: str, *, timeout: int):
            calls.append((endpoint, timeout))
            return {"endpoint": endpoint}

    class _Playwright:
        chromium = _Chromium()

    monkeypatch.setattr(
        live_batch_smoke,
        "compact_cdp_page_targets_if_needed",
        lambda _endpoint: {"triggered": False},
    )
    monkeypatch.setattr(
        live_batch_smoke,
        "_cdp_http_get",
        lambda endpoint, path, *, timeout_seconds: _Response()
        if (endpoint, path, timeout_seconds) == ("http://192.168.15.104:9224", "/json/version", live_batch_smoke.DEFAULT_CDP_HTTP_TIMEOUT_SECONDS)
        else (_ for _ in ()).throw(AssertionError((endpoint, path, timeout_seconds))),
    )

    browser = live_batch_smoke.connect_browser_over_cdp(_Playwright(), "http://192.168.15.104:9224")

    assert browser == {"endpoint": "ws://192.168.15.104:9224/devtools/browser/browser-1"}
    assert calls == [("ws://192.168.15.104:9224/devtools/browser/browser-1", 120000)]

def test_connect_browser_over_cdp_reconnects_after_connection_reset(monkeypatch) -> None:
    calls: list[str] = []

    class _Chromium:
        @staticmethod
        def connect_over_cdp(endpoint: str, *, timeout: int):
            calls.append(f"connect:{endpoint}:{timeout}")
            if len([event for event in calls if event.startswith("connect:")]) == 1:
                raise ConnectionResetError("read ECONNRESET")
            return {"endpoint": endpoint}

    class _Playwright:
        chromium = _Chromium()

    monkeypatch.setenv("FAPAI_CDP_RECONNECT_ATTEMPTS", "3")
    monkeypatch.setenv("FAPAI_CDP_RECONNECT_BACKOFF_SECONDS", "0")
    monkeypatch.setattr(live_batch_smoke, "compact_cdp_page_targets_if_needed", lambda _endpoint: {"triggered": False})
    monkeypatch.setattr(
        live_batch_smoke,
        "resolve_playwright_cdp_endpoint",
        lambda endpoint: calls.append(f"resolve:{endpoint}") or endpoint,
    )
    monkeypatch.setattr(
        live_batch_smoke,
        "_cdp_endpoint_healthy_for_reconnect",
        lambda endpoint: calls.append(f"health:{endpoint}") or True,
    )

    browser = live_batch_smoke.connect_browser_over_cdp(_Playwright(), "http://127.0.0.1:9223")

    assert browser == {"endpoint": "http://127.0.0.1:9223"}
    assert calls == [
        "resolve:http://127.0.0.1:9223",
        "connect:http://127.0.0.1:9223:120000",
        "health:http://127.0.0.1:9223",
        "resolve:http://127.0.0.1:9223",
        "connect:http://127.0.0.1:9223:120000",
    ]

def test_connect_browser_over_cdp_raises_after_bounded_reconnects(monkeypatch) -> None:
    calls: list[str] = []

    class _Chromium:
        @staticmethod
        def connect_over_cdp(endpoint: str, *, timeout: int):
            calls.append(f"connect:{endpoint}:{timeout}")
            raise ConnectionResetError("read ECONNRESET")

    class _Playwright:
        chromium = _Chromium()

    monkeypatch.setenv("FAPAI_CDP_RECONNECT_ATTEMPTS", "2")
    monkeypatch.setenv("FAPAI_CDP_RECONNECT_BACKOFF_SECONDS", "0")
    monkeypatch.setattr(live_batch_smoke, "compact_cdp_page_targets_if_needed", lambda _endpoint: {"triggered": False})
    monkeypatch.setattr(live_batch_smoke, "resolve_playwright_cdp_endpoint", lambda endpoint: endpoint)
    monkeypatch.setattr(
        live_batch_smoke,
        "_cdp_endpoint_healthy_for_reconnect",
        lambda endpoint: calls.append(f"health:{endpoint}") or False,
    )

    with pytest.raises(live_batch_smoke.CdpEndpointUnavailableError) as error:
        live_batch_smoke.connect_browser_over_cdp(_Playwright(), "http://192.168.15.104:9224")

    assert error.value.operation == "connect_over_cdp_bounded_reconnect"
    assert calls == [
        "connect:http://192.168.15.104:9224:120000",
        "health:http://192.168.15.104:9224",
    ]

def test_resolve_playwright_cdp_endpoint_ignores_host_proxy_env(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    closed: list[bool] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {"webSocketDebuggerUrl": "ws://192.168.15.104:9224/devtools/browser/browser-2"}

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True
            self.headers: dict[str, str] = {}

        def get(self, url: str, *, timeout: float):
            assert self.headers["Connection"] == "close"
            calls.append({"url": url, "timeout": timeout, "trust_env": self.trust_env})
            return _Response()

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(
        live_batch_smoke.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("requests.get should not be used")),
    )
    monkeypatch.setattr(live_batch_smoke.requests, "Session", _Session)

    endpoint = live_batch_smoke.resolve_playwright_cdp_endpoint("http://192.168.15.104:9224")

    assert endpoint == "ws://192.168.15.104:9224/devtools/browser/browser-2"
    assert closed == [True]
    assert calls == [
        {
            "url": "http://192.168.15.104:9224/json/version",
            "timeout": live_batch_smoke.DEFAULT_CDP_HTTP_TIMEOUT_SECONDS,
            "trust_env": False,
        }
    ]

def test_resolve_playwright_cdp_endpoint_rewrites_chromium_loopback_websocket(monkeypatch) -> None:
    class _Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {
                "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/browser/browser-remote",
            }

    monkeypatch.setattr(
        live_batch_smoke,
        "_cdp_http_get",
        lambda *_args, **_kwargs: _Response(),
    )

    assert live_batch_smoke.resolve_playwright_cdp_endpoint(
        "http://pc2-browser-solver:9224"
    ) == "ws://pc2-browser-solver:9224/devtools/browser/browser-remote"

def test_resolve_playwright_cdp_endpoint_falls_back_to_cached_websocket_when_http_probe_fails(monkeypatch) -> None:
    class _FakeProbe:
        @staticmethod
        def _load_cached_cdp_websocket(_endpoint: str) -> str:
            return "ws://192.168.15.104:9224/devtools/browser/cached-browser"

    monkeypatch.setattr(
        live_batch_smoke,
        "_cdp_http_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("http 400 /json/version")),
    )
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)

    endpoint = live_batch_smoke.resolve_playwright_cdp_endpoint("http://192.168.15.104:9224")

    assert endpoint == "ws://192.168.15.104:9224/devtools/browser/cached-browser"

def test_read_page_content_with_retries_waits_for_navigation_to_settle() -> None:
    events: list[str] = []

    class FakePage:
        def __init__(self) -> None:
            self.calls = 0

        def locator(self, selector):
            assert selector == "html"
            return self

        def inner_html(self, *, timeout):
            assert timeout > 0
            return self.content()

        def content(self) -> str:
            self.calls += 1
            events.append(f"content:{self.calls}")
            if self.calls == 1:
                raise RuntimeError("Page.content: page is navigating")
            return "<html>ok</html>"

        def wait_for_timeout(self, timeout: int) -> None:
            events.append(f"wait:{timeout}")

    html = live_batch_smoke.read_page_content_with_retries(FakePage(), attempts=3, wait_timeout_ms=250)

    assert html == "<html>ok</html>"
    assert events == ["content:1", "wait:250", "content:2"]

def test_wait_for_detail_ready_returns_when_detail_marker_appears() -> None:
    class FakePage:
        url = "https://sf-item.taobao.com/sf_item/3001.htm"

        def __init__(self) -> None:
            self.contents = [
                "<html><body>shell</body></html>",
                '<html><input id="J_StartPrice" value="100" /></html>',
            ]
            self.waits: list[int] = []

        def locator(self, selector):
            assert selector == "html"
            return self

        def inner_html(self, *, timeout):
            assert timeout > 0
            return self.content()

        def content(self) -> str:
            return self.contents.pop(0) if len(self.contents) > 1 else self.contents[0]

        def wait_for_timeout(self, timeout: int) -> None:
            self.waits.append(timeout)

    page = FakePage()

    html = live_batch_smoke._wait_for_detail_ready(page, timeout_ms=1000, poll_interval_ms=50)

    assert 'id="J_StartPrice"' in html
    assert len(page.waits) == 1
    assert 0 < page.waits[0] <= 50

def test_wait_for_detail_ready_returns_challenge_without_waiting() -> None:
    class FakePage:
        url = "https://login.taobao.com/challenge"

        def locator(self, selector):
            assert selector == "html"
            return self

        def inner_html(self, *, timeout):
            assert timeout > 0
            return self.content()

        def content(self) -> str:
            return "<html>challenge</html>"

        def wait_for_timeout(self, _timeout: int) -> None:
            raise AssertionError("challenge should stop readiness polling")

    html = live_batch_smoke._wait_for_detail_ready(FakePage(), timeout_ms=1000, poll_interval_ms=50)

    assert html == "<html>challenge</html>"

def test_wait_for_detail_ready_returns_last_html_at_bounded_timeout() -> None:
    waits: list[int] = []

    class FakePage:
        url = "https://sf-item.taobao.com/sf_item/3002.htm"

        def locator(self, selector):
            assert selector == "html"
            return self

        def inner_html(self, *, timeout):
            assert timeout > 0
            return self.content()

        def content(self) -> str:
            return "<html><body>shell</body></html>"

        def wait_for_timeout(self, timeout: int) -> None:
            waits.append(timeout)

    html = live_batch_smoke._wait_for_detail_ready(FakePage(), timeout_ms=2, poll_interval_ms=1)

    assert html == "<html><body>shell</body></html>"
    assert len(waits) <= 2

def test_fetch_browser_navigation_list_page_closes_only_shared_owned_page(monkeypatch):
    from tools.test.test_browser_target_capture import capture_fixture, PAYLOADS
    capture, events, _ = capture_fixture(monkeypatch, live_batch_smoke, 'seed')
    assert capture()[0] == PAYLOADS['seed']
    assert events.count('close_owned') == events.count('session_detach') == 1
    assert events.index('configure') < events.index('fresh_request') < events.index('session_detach')

def test_fetch_browser_navigation_list_page_preserves_existing_login_without_opening(monkeypatch):
    from tools.test.test_browser_target_capture import capture_fixture
    capture, events, _ = capture_fixture(monkeypatch, live_batch_smoke, 'seed', old_url='https://login.taobao.com/havanaone/login/login.htm')
    html, url = capture()
    assert live_batch_smoke.is_challenge_page(html, url)
    assert live_batch_smoke.is_login_page(html, url)
    assert 'fresh_request' not in events and 'close_owned' not in events
