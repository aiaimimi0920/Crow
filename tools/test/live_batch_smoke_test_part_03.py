from tools.test.live_batch_smoke_test_context import *  # noqa: F401,F403


def test_fetch_browser_navigation_list_page_preserves_challenge_target_for_solver(monkeypatch) -> None:
    closed_targets: list[str] = []
    target = {
        "id": "challenge-page",
        "url": "https://sf.taobao.com/list/page=2",
        "webSocketDebuggerUrl": "ws://cdp/challenge-page",
    }

    monkeypatch.setattr(taobao_login_health, "compact_cdp_pages_if_needed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(taobao_login_health, "read_cdp_json", lambda *_args, **_kwargs: target)
    monkeypatch.setattr(
        live_batch_smoke,
        "_read_cdp_list_target_html",
        lambda *_args, **_kwargs: (
            "<html><body>captcha challenge</body></html>",
            "https://sec.taobao.com/_____tmd_____/punish?x5secdata=challenge",
        ),
    )
    monkeypatch.setattr(
        taobao_login_health,
        "close_cdp_target",
        lambda _endpoint, target_id: closed_targets.append(str(target_id)),
    )

    html, final_url = live_batch_smoke.fetch_browser_navigation_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page=2",
    )

    assert "challenge" in html
    assert "/punish" in final_url
    assert closed_targets == []

def test_fetch_detail_with_browser_preserves_challenge_page_for_solver(monkeypatch) -> None:
    fake_sync_api = types.ModuleType("playwright.sync_api")
    events: list[str] = []

    class FakePlaywrightContext:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return None

    fake_sync_api.sync_playwright = FakePlaywrightContext
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    class FakeResponse:
        status = 200

    class FakePage:
        url = "https://sec.taobao.com/_____tmd_____/punish?x5secdata=challenge"
        closed = False

        def evaluate(self, _expression):
            events.append("identity:verify")
            return {
                "userAgent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36"
                ),
                "platform": "Win32",
                "uaPlatform": "Windows",
                "webdriver": False,
                "deviceMemory": 8,
                "language": "zh-CN",
            }

        def goto(self, *_args, **_kwargs):
            events.append("navigation:goto")
            return FakeResponse()

        def close(self):
            self.closed = True

    page = FakePage()

    class FakeCdpSession:
        def send(self, method, _params=None):
            events.append(f"identity:{method}")
            if method == "Emulation.setLocaleOverride":
                raise RuntimeError("Another locale override is already in effect")
            return {}

        def detach(self):
            events.append("identity:detach")
            raise RuntimeError("No session with given id")

    class FakeContext:
        def new_page(self):
            return page

        def new_cdp_session(self, target_page):
            assert target_page is page
            return FakeCdpSession()

    class FakeBrowser:
        contexts = [FakeContext()]

    monkeypatch.setattr(live_batch_smoke, "connect_browser_over_cdp", lambda *_args, **_kwargs: FakeBrowser())
    monkeypatch.setattr(live_batch_smoke, "detach_attached_cdp_browser", lambda *_args, **_kwargs: None)
    monkeypatch.setenv(
        "FAPAI_BROWSER_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "Chrome/152.0.0.0 Safari/537.36",
    )
    monkeypatch.setenv("FAPAI_BROWSER_IDENTITY_FULL_VERSION", "152.0.7977.64")
    monkeypatch.setattr(
        live_batch_smoke,
        "_wait_for_detail_ready",
        lambda *_args, **_kwargs: "<html><body>captcha challenge</body></html>",
    )

    with pytest.raises(RuntimeError, match="anti-bot challenge"):
        live_batch_smoke._fetch_detail_with_browser_attached(
            {"id": "3003", "url": "https://sf-item.taobao.com/sf_item/3003.htm"},
            cdp_endpoint="http://127.0.0.1:9223",
        )

    assert page.closed is False
    assert events == [
        "identity:Emulation.setUserAgentOverride",
        "identity:Emulation.setTimezoneOverride",
        "identity:Emulation.setLocaleOverride",
        "identity:Page.addScriptToEvaluateOnNewDocument",
        "identity:Runtime.evaluate",
        "identity:verify",
        "navigation:goto",
        "identity:detach",
    ]


def test_fetch_detail_with_browser_preserves_existing_login_without_opening_another_page(
    monkeypatch,
) -> None:
    fake_sync_api = types.ModuleType("playwright.sync_api")

    class FakePlaywrightContext:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return None

    fake_sync_api.sync_playwright = FakePlaywrightContext
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    class ExistingPage:
        url = "https://login.taobao.com/member/login.jhtml"
        brought_to_front = False

        def bring_to_front(self):
            self.brought_to_front = True

        @staticmethod
        def content():
            return "<html>_____tmd_____/punish x5secdata=challenge</html>"

    existing_page = ExistingPage()

    class FakeContext:
        pages = [existing_page]

        @staticmethod
        def new_page():
            raise AssertionError("an unresolved challenge must not open another detail page")

    class FakeBrowser:
        contexts = [FakeContext()]

    monkeypatch.setattr(live_batch_smoke, "connect_browser_over_cdp", lambda *_args, **_kwargs: FakeBrowser())
    monkeypatch.setattr(live_batch_smoke, "detach_attached_cdp_browser", lambda *_args, **_kwargs: None)

    with pytest.raises(live_batch_smoke.DetailChallengeError, match="anti-bot challenge"):
        live_batch_smoke._fetch_detail_with_browser_attached(
            {"id": "3004", "url": "https://sf-item.taobao.com/sf_item/3004.htm"},
            cdp_endpoint="http://127.0.0.1:9223",
        )

    assert existing_page.brought_to_front is False

def test_fetch_browser_list_page_falls_back_to_navigation_when_open_page_probe_closes(monkeypatch) -> None:
    events: list[str] = []

    def _open_page(_cdp_endpoint: str, _target_url: str, **_kwargs):
        events.append("open_page")
        raise RuntimeError("Page.wait_for_timeout: Target page, context or browser has been closed")

    def _navigation_page(_cdp_endpoint: str, target_url: str):
        events.append("navigation_page")
        return "<html>ok</html>", target_url

    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_list_page", _open_page)
    monkeypatch.setattr(live_batch_smoke, "fetch_browser_navigation_list_page", _navigation_page)

    html, final_url = live_batch_smoke.fetch_browser_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page=2",
    )

    assert html == "<html>ok</html>"
    assert final_url == "https://sf.taobao.com/list/page=2"
    assert events == ["open_page", "navigation_page"]

def test_is_challenge_page_detects_challenge_url_without_summary_markers(monkeypatch) -> None:
    class _FakeProbe:
        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            assert final_url == "https://contest.local/challenge?ticket=abc"
            return {
                "body_has_login": False,
                "body_has_challenge": False,
            }

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)

    assert live_batch_smoke.is_challenge_page(
        "<html><body>normal body</body></html>",
        "https://contest.local/challenge?ticket=abc",
    )

def test_fetch_open_browser_list_page_reuses_resolved_cdp_target_after_solver_bg_param_is_removed(monkeypatch) -> None:
    events: list[str] = []

    def _fail_sync_playwright():
        raise AssertionError("playwright path should not be used for open list-page reuse")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = _fail_sync_playwright
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    monkeypatch.setattr(
        taobao_login_health,
        "list_cdp_targets",
        lambda _endpoint: [
            {
                "id": "page-5",
                "type": "page",
                "url": "https://sf.taobao.com/list/50025969__2.htm?location_code=530121&st_param=1&auction_start_seg=-1&page=5",
                "webSocketDebuggerUrl": "ws://cdp/page-5",
            }
        ],
    )
    monkeypatch.setattr(
        taobao_login_health,
        "activate_cdp_target",
        lambda endpoint, target: events.append(f"activate:{endpoint}:{target['id']}"),
    )
    monkeypatch.setattr(
        taobao_login_health,
        "evaluate_cdp_expression",
        lambda websocket_url, expression: events.append(f"evaluate:{websocket_url}") or {
            "result": {
                "result": {
                    "value": {
                        "html": "<html><script>var sf-item-list-data = {};</script></html>",
                        "url": "https://sf.taobao.com/list/50025969__2.htm?location_code=530121&st_param=1&auction_start_seg=-1&page=5",
                    }
                }
            }
        },
    )

    html, final_url = live_batch_smoke.fetch_open_browser_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=530121&st_param=1&auction_start_seg=-1&page=5&__captcha_solver_bg=1",
    )

    assert "sf-item-list-data" in html
    assert final_url == "https://sf.taobao.com/list/50025969__2.htm?location_code=530121&st_param=1&auction_start_seg=-1&page=5"
    assert events == [
        "activate:http://127.0.0.1:9223:page-5",
        "evaluate:ws://cdp/page-5",
    ]

def test_fetch_open_browser_list_page_skips_punish_url_after_normalization_via_cdp_target(monkeypatch) -> None:
    events: list[str] = []

    def _fail_sync_playwright():
        raise AssertionError("playwright path should not be used for punish-url matching")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = _fail_sync_playwright
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    punish_url = (
        "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish"
        "?x5secdata=abc&location_code=530121&st_param=1&auction_start_seg=-1&page=5&__captcha_solver_bg=1"
    )
    monkeypatch.setattr(
        taobao_login_health,
        "list_cdp_targets",
        lambda _endpoint: [
            {
                "id": "page-punish",
                "type": "page",
                "url": punish_url,
                "webSocketDebuggerUrl": "ws://cdp/page-punish",
            }
        ],
    )
    monkeypatch.setattr(
        taobao_login_health,
        "activate_cdp_target",
        lambda endpoint, target: events.append(f"activate:{endpoint}:{target['id']}"),
    )
    monkeypatch.setattr(
        taobao_login_health,
        "evaluate_cdp_expression",
        lambda websocket_url, expression: events.append(f"evaluate:{websocket_url}") or {
            "result": {
                "result": {
                    "value": {
                        "html": "<html><script>var sf-item-list-data = {};</script></html>",
                        "url": punish_url,
                    }
                }
            }
        },
    )

    result = live_batch_smoke.fetch_open_browser_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=530121&st_param=1&auction_start_seg=-1&page=5",
    )

    assert result is None
    assert events == [
        "activate:http://127.0.0.1:9223:page-punish",
        "evaluate:ws://cdp/page-punish",
    ]

def test_normalize_browser_match_url_collapses_duplicate_path_slashes() -> None:
    result = live_batch_smoke._normalize_browser_match_url(
        "https://sf-item.taobao.com//sf_item/598568414650.htm?foo=1&__captcha_solver_bg=1#details"
    )

    assert result == "https://sf-item.taobao.com/sf_item/598568414650.htm?foo=1"

def test_fetch_open_browser_list_page_skips_login_then_uses_second_valid_target(monkeypatch) -> None:
    read_targets: list[str] = []

    monkeypatch.setattr(
        live_batch_smoke,
        "_find_matching_cdp_list_targets",
        lambda _cdp_endpoint, _target_url: [
            {"id": "login-page"},
            {"id": "healthy-page"},
        ],
    )

    def _read_target(_cdp_endpoint: str, target: dict[str, str]) -> tuple[str, str]:
        read_targets.append(target["id"])
        if target["id"] == "login-page":
            return "<html>淘宝登录</html>", "https://login.taobao.com/member/login.jhtml"
        return (
            "<html><script>var sf-item-list-data = {};</script><body>ok</body></html>",
            "https://sf.taobao.com/list/page=8",
        )

    monkeypatch.setattr(live_batch_smoke, "_read_cdp_list_target_html", _read_target)

    html, final_url = live_batch_smoke.fetch_open_browser_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page=8",
    )

    assert "sf-item-list-data" in html
    assert final_url == "https://sf.taobao.com/list/page=8"
    assert read_targets == ["login-page", "healthy-page"]

def test_fetch_browser_list_page_falls_back_to_navigation_after_login_html(monkeypatch) -> None:
    events: list[str] = []

    def _open_page(_cdp_endpoint: str, _target_url: str, **_kwargs):
        events.append("open_page")
        return None

    def _navigation_page(_cdp_endpoint: str, target_url: str):
        events.append("navigation_page")
        return "<html>ok</html>", target_url

    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_list_page", _open_page)
    monkeypatch.setattr(live_batch_smoke, "fetch_browser_navigation_list_page", _navigation_page)

    html, final_url = live_batch_smoke.fetch_browser_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page=9",
    )

    assert html == "<html>ok</html>"
    assert final_url == "https://sf.taobao.com/list/page=9"
    assert events == ["open_page", "navigation_page"]

def test_fetch_browser_list_page_reuses_existing_challenge_without_navigation(monkeypatch) -> None:
    challenge_page = (
        "<html>_____tmd_____/punish challenge</html>",
        "https://sf.taobao.com//list/page=9/_____tmd_____/punish?x5step=1",
    )
    calls: list[tuple[str, bool]] = []

    def _open_page(
        _cdp_endpoint: str,
        _target_url: str,
        *,
        include_challenge: bool = False,
    ):
        calls.append(("open_page", include_challenge))
        return challenge_page

    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_list_page", _open_page)
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_browser_navigation_list_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an existing challenge page must not open another CDP target")
        ),
    )

    result = live_batch_smoke.fetch_browser_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page=9",
    )

    assert result == challenge_page
    assert calls == [("open_page", True)]
