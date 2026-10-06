from tools.test.live_batch_smoke_test_context import *  # noqa: F401,F403


def test_compact_cdp_page_targets_keeps_browser_alive_at_limit(monkeypatch) -> None:
    calls: list[str] = []

    class _Response:
        def __init__(self, payload: object):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self._payload

    def _get(endpoint: str, path: str, *, timeout_seconds: float):
        calls.append(f"{endpoint}{path}")
        if path == "/json/list":
            return _Response(
                [
                    {"id": "page-1", "type": "page", "url": "https://sf.taobao.com/"},
                    {"id": "page-2", "type": "page", "url": "about:blank"},
                    {"id": "worker-1", "type": "service_worker", "url": "chrome-extension://x"},
                    {"id": "page-3", "type": "page", "url": "https://sf.taobao.com/list/1"},
                ]
            )
        return _Response({})

    def _put(endpoint: str, path: str, *, timeout_seconds: float):
        calls.append(f"PUT {endpoint}{path}")
        if path == "/json/new?about:blank":
            return _Response({"id": "keepalive-page"})
        return _Response({})

    monkeypatch.setattr(live_batch_smoke, "_cdp_http_get", _get)
    monkeypatch.setattr(live_batch_smoke, "_cdp_http_put", _put)

    summary = live_batch_smoke.compact_cdp_page_targets_if_needed("http://127.0.0.1:9223", limit=3)

    assert summary["triggered"] is True
    assert summary["page_count"] == 3
    assert summary["closed"] == 3
    assert summary["keepalive_target_id"] == "keepalive-page"
    assert calls == [
        "http://127.0.0.1:9223/json/list",
        "PUT http://127.0.0.1:9223/json/new?about:blank",
        "http://127.0.0.1:9223/json/close/page-1",
        "http://127.0.0.1:9223/json/close/page-2",
        "http://127.0.0.1:9223/json/close/page-3",
    ]

def test_compact_cdp_page_targets_does_not_close_below_limit(monkeypatch) -> None:
    calls: list[str] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return [
                {"id": "page-1", "type": "page", "url": "https://sf.taobao.com/"},
                {"id": "page-2", "type": "page", "url": "https://sf.taobao.com/list/1"},
            ]

    def _get(endpoint: str, path: str, *, timeout_seconds: float):
        calls.append(f"{endpoint}{path}")
        return _Response()

    monkeypatch.setattr(live_batch_smoke, "_cdp_http_get", _get)

    summary = live_batch_smoke.compact_cdp_page_targets_if_needed("http://127.0.0.1:9223", limit=3)

    assert summary == {"triggered": False, "page_count": 2, "closed": 0, "errors": []}
    assert calls == ["http://127.0.0.1:9223/json/list"]

def test_load_open_browser_pages_returns_empty_when_cdp_page_cache_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_open_browser_pages",
        lambda _endpoint: (_ for _ in ()).throw(RuntimeError("cdp unstable")),
    )

    pages = live_batch_smoke.load_open_browser_pages("http://127.0.0.1:9223")

    assert pages == {}

def test_fetch_list_page_falls_back_to_open_browser_page(monkeypatch) -> None:
    class _FailingHttp:
        @staticmethod
        def get(*_args, **_kwargs):
            import requests

            raise requests.exceptions.ProxyError("proxy exhausted")

    monkeypatch.setattr(live_batch_smoke, "fetch_browser_list_page", lambda cdp_endpoint, target_url: ("<html>browser-list</html>", target_url))

    html, final_url, status, method = live_batch_smoke.fetch_list_page(
        _FailingHttp(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
    )

    assert html == "<html>browser-list</html>"
    assert final_url == "https://sf.taobao.com/list/page"
    assert status is None
    assert method == "browser_page"

def test_fetch_browser_navigation_list_page_wraps_cdp_target_open_timeout(monkeypatch) -> None:
    monkeypatch.setattr(
        "tools.cdp_background_page.open_background_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("timed out")),
    )

    with pytest.raises(live_batch_smoke.CdpEndpointUnavailableError) as excinfo:
        live_batch_smoke.fetch_browser_navigation_list_page(
            "http://127.0.0.1:9223",
            "https://sf.taobao.com/list/page",
        )

    assert excinfo.value.cdp_endpoint == "http://127.0.0.1:9223"
    assert excinfo.value.operation == "open_list_page_target"

def test_fetch_list_page_falls_back_to_browser_when_http_returns_punish(monkeypatch) -> None:
    class _ChallengeResponse:
        text = "<script>location.href='_____tmd_____/punish?x5secdata=abc'</script>"
        url = "https://sf.taobao.com/list/page=2"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _ChallengeHttp:
        @staticmethod
        def get(*_args, **_kwargs):
            return _ChallengeResponse()

    monkeypatch.setattr(live_batch_smoke, "fetch_browser_list_page", lambda cdp_endpoint, target_url: ("<html>browser-ok</html>", target_url))

    html, final_url, status, method = live_batch_smoke.fetch_list_page(
        _ChallengeHttp(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=2",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
    )

    assert html == "<html>browser-ok</html>"
    assert final_url == "https://sf.taobao.com/list/page=2"
    assert status is None
    assert method == "browser_page_after_http_challenge"

def test_fetch_list_page_honors_list_http_timeout_env(monkeypatch) -> None:
    captured: list[float] = []

    class _OkResponse:
        text = "<html><script>var sf-item-list-data = {}</script></html>"
        url = "https://sf.taobao.com/list/page=2"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _Http:
        @staticmethod
        def get(*_args, **kwargs):
            captured.append(kwargs["timeout"])
            return _OkResponse()

    monkeypatch.setenv("FAPAI_LIST_HTTP_TIMEOUT_SECONDS", "8")

    html, final_url, status, method = live_batch_smoke.fetch_list_page(
        _Http(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=2",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
    )

    assert "sf-item-list-data" in html
    assert final_url == "https://sf.taobao.com/list/page=2"
    assert status == 200
    assert method == "http_cookie"
    assert captured == [8.0]

def test_fetch_list_page_can_disable_browser_fallback_for_http_challenge(monkeypatch) -> None:
    class _ChallengeResponse:
        text = "<script>location.href='_____tmd_____/punish?x5secdata=abc'</script>"
        url = "https://sf.taobao.com/list/page=2"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _ChallengeHttp:
        @staticmethod
        def get(*_args, **_kwargs):
            return _ChallengeResponse()

    monkeypatch.setenv("FAPAI_LIST_BROWSER_FALLBACK", "0")
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_browser_list_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser fallback should be disabled")),
    )

    html, final_url, status, method = live_batch_smoke.fetch_list_page(
        _ChallengeHttp(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=2",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
    )

    assert html == _ChallengeResponse.text
    assert final_url == "https://sf.taobao.com/list/page=2"
    assert status == 200
    assert method == "http_cookie_challenge"

def test_fetch_list_page_reports_solver_when_browser_fallback_disabled(monkeypatch) -> None:
    class _ChallengeResponse:
        text = "<script>location.href='_____tmd_____/punish?x5secdata=abc'</script>"
        url = "https://sf.taobao.com/list/page=2"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _ChallengeHttp:
        @staticmethod
        def get(*_args, **_kwargs):
            return _ChallengeResponse()

    report_calls: list[tuple[str, str, dict[str, object]]] = []

    monkeypatch.setenv("FAPAI_LIST_BROWSER_FALLBACK", "0")
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_browser_list_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser fallback should be disabled")),
    )
    monkeypatch.setattr(
        live_batch_smoke,
        "request_captcha_solver",
        lambda cdp_endpoint, target_url, **kwargs: report_calls.append((cdp_endpoint, target_url, kwargs))
        or {"status": "solving"},
    )

    html, final_url, status, method = live_batch_smoke.fetch_list_page(
        _ChallengeHttp(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=2",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
        solver_enabled=True,
    )

    assert html == _ChallengeResponse.text
    assert final_url == "https://sf.taobao.com/list/page=2"
    assert status == 200
    assert method == "http_cookie_challenge"
    assert report_calls == [
        (
            "http://127.0.0.1:9223",
            "https://sf.taobao.com/list/page=2",
            {"api_base_url": None, "manual_only": False},
        )
    ]

def test_fetch_list_page_reports_login_redirect_as_manual_auth_handoff(monkeypatch) -> None:
    class _LoginResponse:
        text = "<html>淘宝登录</html>"
        url = "https://login.taobao.com/havanaone/login/login.htm?redirect=https://sf.taobao.com/list/page=12"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _LoginHttp:
        @staticmethod
        def get(*_args, **_kwargs):
            return _LoginResponse()

    report_calls: list[tuple[str, str, dict[str, object]]] = []

    monkeypatch.setenv("FAPAI_LIST_BROWSER_FALLBACK", "0")
    monkeypatch.setattr(
        live_batch_smoke,
        "request_captcha_solver",
        lambda cdp_endpoint, target_url, **kwargs: report_calls.append((cdp_endpoint, target_url, kwargs))
        or {"status": "manual_required"},
    )

    html, final_url, status, method = live_batch_smoke.fetch_list_page(
        _LoginHttp(),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/page=12",
        user_agent=live_batch_smoke.DEFAULT_USER_AGENT,
        solver_enabled=True,
    )

    assert html == _LoginResponse.text
    assert final_url == _LoginResponse.url
    assert status == 200
    assert method == "http_cookie_challenge"
    assert report_calls == [
        (
            "http://127.0.0.1:9223",
            "https://sf.taobao.com/list/page=12",
            {"api_base_url": None, "manual_only": True},
        )
    ]

def test_request_captcha_solver_uses_default_api_base_and_normalizes_non_dict_response(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        taobao_login_health,
        "build_captcha_solver_target_url",
        lambda target_url: calls.append(("build", target_url)) or "https://contest.local/auth?__captcha_solver_bg=1",
    )
    monkeypatch.setattr(
        taobao_login_health,
        "report_captcha_via_api",
        lambda api_base_url, cdp_endpoint, target_url: calls.append(
            ("report", {"api_base_url": api_base_url, "cdp_endpoint": cdp_endpoint, "target_url": target_url})
        )
        or ["queued"],
    )

    result = live_batch_smoke.request_captcha_solver(
        "http://127.0.0.1:9223",
        "https://contest.local/auth",
    )

    assert result == {"status": "unknown_response", "raw": ["queued"]}
    assert calls == [
        ("build", "https://contest.local/auth"),
        (
            "report",
            {
                "api_base_url": live_batch_smoke.DEFAULT_API_BASE_URL,
                "cdp_endpoint": "http://127.0.0.1:9223",
                "target_url": "https://contest.local/auth?__captcha_solver_bg=1",
            },
        ),
    ]

def test_request_captcha_solver_preserves_dict_response_and_explicit_api_base(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    target_url = "https://contest.local/auth?__captcha_solver_bg=1"

    monkeypatch.setattr(
        taobao_login_health,
        "build_captcha_solver_target_url",
        lambda url: calls.append(("build", url)) or target_url,
    )
    monkeypatch.setattr(
        taobao_login_health,
        "report_captcha_via_api",
        lambda api_base_url, cdp_endpoint, solver_target_url: calls.append(
            (
                "report",
                {
                    "api_base_url": api_base_url,
                    "cdp_endpoint": cdp_endpoint,
                    "target_url": solver_target_url,
                },
            )
        )
        or {"status": "already_running", "target_url": solver_target_url},
    )

    result = live_batch_smoke.request_captcha_solver(
        "http://127.0.0.1:9223",
        target_url,
        api_base_url="http://collection-api.test/api",
    )

    assert result == {"status": "already_running", "target_url": target_url}
    assert calls == [
        ("build", target_url),
        (
            "report",
            {
                "api_base_url": "http://collection-api.test/api",
                "cdp_endpoint": "http://127.0.0.1:9223",
                "target_url": target_url,
            },
        ),
    ]

def test_request_captcha_solver_keeps_real_taobao_on_automatic_solver_path(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        taobao_login_health,
        "build_captcha_solver_target_url",
        lambda url: url,
    )

    def _report(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"status": "manual_required"}

    monkeypatch.setattr(taobao_login_health, "report_captcha_via_api", _report)

    result = live_batch_smoke.request_captcha_solver(
        "http://127.0.0.1:9225",
        "https://sf-item.taobao.com/sf_item/3001.htm",
        api_base_url="http://collection-api.test/api",
    )

    assert result == {"status": "manual_required"}
    assert captured["kwargs"] == {}
