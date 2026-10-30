from __future__ import annotations

from tools.test.browserless_seed_probe_test_context import *


def test_summarize_list_page_extracts_live_like_payload_without_false_login_signal():
    summary = browserless_seed_probe.summarize_list_page(
        LIVE_LIKE_LIST_HTML,
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    assert summary["has_script"] is True
    assert summary["item_count"] == 2
    assert summary["first_ids"] == [747988656830, 660720568820]
    assert summary["first_urls"] == [
        "//sf-item.taobao.com/sf_item/747988656830.htm?track_id=demo-1",
        "//sf-item.taobao.com/sf_item/660720568820.htm?track_id=demo-2",
    ]
    assert summary["body_has_login"] is False
    assert summary["body_has_captcha"] is False


def test_summarize_list_page_prefers_valid_payload_over_hidden_generic_captcha_copy():
    html = LIVE_LIKE_LIST_HTML.replace("</body>", "<div hidden>验证码</div></body>")

    summary = browserless_seed_probe.summarize_list_page(
        html,
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    assert summary["has_script"] is True
    assert summary["item_count"] == 2
    assert summary["body_has_captcha"] is False
    assert summary["body_has_challenge"] is False


def test_summarize_list_page_marks_login_page_from_final_url():
    summary = browserless_seed_probe.summarize_list_page(
        LOGIN_HTML,
        final_url="https://login.taobao.com/havanaone/login/login.htm?bizName=taobao",
    )

    assert summary["has_script"] is False
    assert summary["item_count"] is None
    assert summary["body_has_login"] is True


def test_summarize_list_page_marks_x5sec_punish_page_as_challenge():
    summary = browserless_seed_probe.summarize_list_page(
        PUNISH_HTML,
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    assert summary["has_script"] is False
    assert summary["body_has_punish"] is True
    assert summary["body_has_challenge"] is True


def test_summarize_list_page_marks_punish_final_url_as_challenge_even_when_html_shell_hides_tokens():
    summary = browserless_seed_probe.summarize_list_page(
        "<html><head><meta charset='utf-8'></head><body>browser shell</body></html>",
        final_url="https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?x5secdata=abc",
    )

    assert summary["has_script"] is False
    assert summary["body_has_punish"] is True
    assert summary["body_has_challenge"] is True


def test_summarize_list_page_redacts_x5secdata_from_body_snippet():
    summary = browserless_seed_probe.summarize_list_page(
        PUNISH_HTML,
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    assert "x5secdata" not in summary["body_snippet"]
    assert "demo" not in summary["body_snippet"]
    assert "taobao_security_value=<redacted>" in summary["body_snippet"]


def test_summarize_list_page_marks_additional_human_verification_markers_as_challenge():
    markers = ("滑动验证", "人机验证", "异常流量", "访问受限")

    for marker in markers:
        summary = browserless_seed_probe.summarize_list_page(
            f"<html><body>{marker}，请稍后重试</body></html>",
            final_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
        )

        assert summary["has_script"] is False
        assert summary["body_has_captcha"] is True
        assert summary["body_has_challenge"] is True


def test_build_session_from_playwright_cookies_adds_cookie_values():
    session = browserless_seed_probe.build_session_from_playwright_cookies(
        [
            {"name": "cookie2", "value": "abc", "domain": ".taobao.com", "path": "/"},
            {"name": "_tb_token_", "value": "xyz", "domain": ".taobao.com", "path": "/"},
        ]
    )

    cookie_map = {(cookie.name, cookie.domain, cookie.path): cookie.value for cookie in session.cookies}

    assert cookie_map[("cookie2", ".taobao.com", "/")] == "abc"
    assert cookie_map[("_tb_token_", ".taobao.com", "/")] == "xyz"
    assert session.trust_env is False


def test_filter_cdp_cookies_to_requested_origins():
    cookies = [
        {"name": "cookie2", "domain": ".taobao.com"},
        {"name": "XSRF-TOKEN", "domain": "login.taobao.com"},
        {"name": "MUID", "domain": ".bing.com"},
    ]

    filtered = browserless_seed_probe.filter_cdp_cookies_to_origins(
        cookies,
        ("https://sf.taobao.com", "https://login.taobao.com"),
    )

    assert filtered == [
        {"name": "cookie2", "domain": ".taobao.com"},
        {"name": "XSRF-TOKEN", "domain": "login.taobao.com"},
    ]


def test_export_cdp_cookies_falls_back_to_raw_websocket_when_playwright_export_fails(monkeypatch):
    monkeypatch.setattr(
        browserless_seed_probe,
        "_export_cdp_cookies_via_playwright",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("playwright timeout")),
    )
    monkeypatch.setattr(
        browserless_seed_probe,
        "_export_cdp_cookies_via_websocket",
        lambda *_args, **_kwargs: [{"name": "cookie2", "domain": ".taobao.com"}],
    )

    cookies = browserless_seed_probe.export_cdp_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "cookie2", "domain": ".taobao.com"}]


def test_export_cdp_cookies_prefers_raw_websocket_before_playwright_when_available(monkeypatch):
    calls: list[str] = []

    def _websocket_export(*_args, **_kwargs):
        calls.append("websocket")
        return [{"name": "cookie2", "domain": ".taobao.com"}]

    def _playwright_export(*_args, **_kwargs):
        calls.append("playwright")
        return [{"name": "playwright-cookie", "domain": ".taobao.com"}]

    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_websocket", _websocket_export)
    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_playwright", _playwright_export)

    cookies = browserless_seed_probe.export_cdp_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "cookie2", "domain": ".taobao.com"}]
    assert calls == ["websocket"]


def test_export_cdp_cookies_falls_back_to_playwright_when_websocket_export_fails(monkeypatch):
    calls: list[str] = []

    def _websocket_export(*_args, **_kwargs):
        calls.append("websocket")
        raise RuntimeError("ws blocked")

    def _playwright_export(*_args, **_kwargs):
        calls.append("playwright")
        return [{"name": "cookie2", "domain": ".taobao.com"}]

    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_websocket", _websocket_export)
    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_playwright", _playwright_export)

    cookies = browserless_seed_probe.export_cdp_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "cookie2", "domain": ".taobao.com"}]
    assert calls == ["websocket", "playwright"]


def test_export_cdp_cookies_reconnects_after_connection_reset(monkeypatch):
    calls: list[str] = []
    websocket_attempts = [ConnectionResetError("connection reset"), [{"name": "cookie2", "domain": ".taobao.com"}]]

    def websocket_export(*_args, **_kwargs):
        calls.append("websocket")
        result = websocket_attempts.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def playwright_export(*_args, **_kwargs):
        calls.append("playwright")
        raise ConnectionResetError("read ECONNRESET")

    monkeypatch.setenv("FAPAI_CDP_RECONNECT_ATTEMPTS", "3")
    monkeypatch.setenv("FAPAI_CDP_RECONNECT_BACKOFF_SECONDS", "0")
    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_websocket", websocket_export)
    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_playwright", playwright_export)
    monkeypatch.setattr(
        browserless_seed_probe,
        "cdp_endpoint_is_healthy",
        lambda endpoint: calls.append(f"health:{endpoint}") or True,
    )

    cookies = browserless_seed_probe.export_cdp_cookies("http://192.168.15.104:9224")

    assert cookies == [{"name": "cookie2", "domain": ".taobao.com"}]
    assert calls == [
        "websocket",
        "playwright",
        "health:http://192.168.15.104:9224",
        "websocket",
    ]


def test_export_cdp_cookies_stops_after_bounded_reconnect_attempts(monkeypatch):
    calls: list[str] = []

    def fail(transport: str):
        def _fail(*_args, **_kwargs):
            calls.append(transport)
            raise ConnectionResetError(transport)

        return _fail

    monkeypatch.setenv("FAPAI_CDP_RECONNECT_ATTEMPTS", "2")
    monkeypatch.setenv("FAPAI_CDP_RECONNECT_BACKOFF_SECONDS", "0")
    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_websocket", fail("websocket"))
    monkeypatch.setattr(browserless_seed_probe, "_export_cdp_cookies_via_playwright", fail("playwright"))
    monkeypatch.setattr(
        browserless_seed_probe,
        "cdp_endpoint_is_healthy",
        lambda endpoint: calls.append(f"health:{endpoint}") or False,
    )

    with pytest.raises(RuntimeError, match="2 bounded attempts"):
        browserless_seed_probe.export_cdp_cookies("http://192.168.15.104:9224")

    assert calls == [
        "websocket",
        "playwright",
        "health:http://192.168.15.104:9224",
    ]


def test_browserless_seed_probe_imports_when_playwright_is_not_installed(monkeypatch):
    real_import = builtins.__import__

    def import_without_playwright(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api" or name.startswith("playwright."):
            raise ModuleNotFoundError("No module named 'playwright'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_playwright)

    module_path = Path(browserless_seed_probe.__file__)
    spec = importlib.util.spec_from_file_location("browserless_seed_probe_no_playwright", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.sync_playwright is None


def test_export_cdp_cookies_playwright_fallback_uses_bounded_cdp_connect_timeout(monkeypatch):
    events: list[object] = []

    class FakeBrowser:
        contexts = []

        def close(self) -> None:
            events.append("browser_close")

    class FakeChromium:
        def connect_over_cdp(self, endpoint: str, timeout: int | None = None) -> FakeBrowser:
            events.append((endpoint, timeout))
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            events.append("playwright_close")

    monkeypatch.setattr(browserless_seed_probe, "sync_playwright", lambda: FakeSyncPlaywright())

    cookies = browserless_seed_probe._export_cdp_cookies_via_playwright(
        "http://127.0.0.1:9223",
        ("https://sf.taobao.com", "https://login.taobao.com"),
    )

    assert cookies == []
    assert events == [
        ("http://127.0.0.1:9223", browserless_seed_probe.DEFAULT_CDP_CONNECT_TIMEOUT_MS),
        "playwright_close",
    ]


def test_export_cdp_cookies_websocket_probe_ignores_host_proxy_env(monkeypatch):
    calls: list[dict[str, object]] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {"webSocketDebuggerUrl": "ws://127.0.0.1:9224/devtools/browser/browser-1"}

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True
            self.close_calls = 0

        def get(self, url: str, *, timeout: int):
            calls.append({"url": url, "timeout": timeout, "trust_env": self.trust_env})
            return _Response()

        def close(self) -> None:
            self.close_calls += 1

    class _FakeWebSocket:
        def settimeout(self, _timeout: float) -> None:
            pass

        def send(self, _payload: str) -> None:
            return None

        @staticmethod
        def recv() -> str:
            return json.dumps({"id": 1, "result": {"cookies": [{"name": "cookie2", "domain": ".taobao.com"}]}})

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        browserless_seed_probe.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("requests.get should not be used")),
    )
    session = _Session()
    monkeypatch.setattr(browserless_seed_probe.requests, "Session", lambda: session)
    monkeypatch.setattr(browserless_seed_probe.websocket, "create_connection", lambda *_args, **_kwargs: _FakeWebSocket())

    cookies = browserless_seed_probe._export_cdp_cookies_via_websocket(
        "http://127.0.0.1:9224",
        ("https://sf.taobao.com", "https://login.taobao.com"),
    )

    assert cookies == [{"name": "cookie2", "domain": ".taobao.com"}]
    assert session.close_calls == 1
    assert calls == [
        {
            "url": "http://127.0.0.1:9224/json/version",
            "timeout": 10,
            "trust_env": False,
        }
    ]


def test_rewrite_cdp_websocket_url_uses_remote_http_endpoint_authority() -> None:
    assert browserless_seed_probe.rewrite_cdp_websocket_url(
        "http://pc2-browser-solver:9224",
        "ws://127.0.0.1:9223/devtools/browser/browser-1",
    ) == "ws://pc2-browser-solver:9224/devtools/browser/browser-1"
    assert browserless_seed_probe.rewrite_cdp_websocket_url(
        "http://192.168.15.104:9224",
        "ws://browser.example:9223/devtools/browser/browser-1",
    ) == "ws://browser.example:9223/devtools/browser/browser-1"


def test_resolve_cdp_endpoint_rewrites_chromium_loopback_websocket(monkeypatch) -> None:
    class _Response:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, str]:
            return {
                "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/browser/browser-remote",
            }

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True
            self.close_calls = 0

        def get(self, _url: str, *, timeout: int) -> _Response:
            assert timeout == 10
            assert self.trust_env is False
            return _Response()

        def close(self) -> None:
            self.close_calls += 1

    session = _Session()
    monkeypatch.setattr(browserless_seed_probe.requests, "Session", lambda: session)

    assert browserless_seed_probe._resolve_cdp_endpoint(
        "http://pc2-browser-solver:9224"
    ) == "ws://pc2-browser-solver:9224/devtools/browser/browser-remote"
    assert session.close_calls == 1
