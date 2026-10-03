from tools.test.taobao_login_health_test_context import *  # noqa: F401,F403


def test_taobao_login_health_bootstraps_repo_path_before_tools_import() -> None:
    script = REPO_ROOT.joinpath("tools", "taobao_login_health.py").read_text(encoding="utf-8")

    assert script.index("REPO_ROOT =") < script.index("from tools.internal_api_http import post_json")

def test_build_captcha_solver_target_url_normalizes_duplicate_path_slashes() -> None:
    result = taobao_login_health.build_captcha_solver_target_url(
        "https://sf-item.taobao.com//sf_item/598568414650.htm?foo=1#details"
    )

    assert result == (
        "https://sf-item.taobao.com/sf_item/598568414650.htm"
        "?foo=1&__captcha_solver_bg=1#details"
    )

def test_build_captcha_solver_target_url_keeps_existing_solver_marker_once() -> None:
    result = taobao_login_health.build_captcha_solver_target_url(
        "https://sf-item.taobao.com//sf_item/598568414650.htm?__captcha_solver_bg=1"
    )

    assert result == (
        "https://sf-item.taobao.com/sf_item/598568414650.htm?__captcha_solver_bg=1"
    )

def test_compact_cdp_pages_keeps_browser_alive_when_triggered(monkeypatch) -> None:
    closed_targets: list[object] = []
    monkeypatch.setenv("FAPAI_CDP_MAX_PAGE_TARGETS", "3")
    monkeypatch.setattr(
        taobao_login_health,
        "open_cdp_keepalive_tab",
        lambda _endpoint: "keepalive-page",
    )
    monkeypatch.setattr(
        taobao_login_health,
        "close_cdp_target",
        lambda _endpoint, target_id: closed_targets.append(target_id) or True,
    )

    summary = taobao_login_health.compact_cdp_pages_if_needed(
        "http://127.0.0.1:9223",
        [
            {"id": "page-1", "type": "page"},
            {"id": "page-2", "type": "page"},
            {"id": "worker-1", "type": "service_worker"},
            {"id": "page-3", "type": "page"},
        ],
    )

    assert summary == {
        "triggered": True,
        "page_count": 3,
        "closed": 3,
        "keepalive_target_id": "keepalive-page",
    }
    assert closed_targets == ["page-1", "page-2", "page-3"]

def test_report_captcha_via_api_prefers_explicit_report_cdp_endpoint_override(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post_json(url: str, payload: dict[str, object], *, timeout: float):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["payload"] = dict(payload)
        return {"status": "queued"}

    monkeypatch.setenv("FAPAI_REPORT_CDP_ENDPOINT", "http://192.168.15.104:9224")
    monkeypatch.setenv("FAPAI_NODE_ID", "pc2")
    monkeypatch.setattr(taobao_login_health, "post_json", _fake_post_json)

    result = taobao_login_health.report_captcha_via_api(
        "http://192.168.15.200:8001/api",
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/page",
        scope="detail",
    )

    assert result == {"status": "queued"}
    assert captured["url"] == "http://192.168.15.200:8001/api/report_captcha"
    assert captured["timeout"] == 10
    assert captured["payload"]["cdp_endpoint"] == "http://192.168.15.104:9224"
    assert captured["payload"]["node_id"] == "pc2"
    assert captured["payload"]["url"] == "https://sf.taobao.com/list/page"
    assert captured["payload"]["scope"] == "detail"

def test_report_captcha_via_api_can_request_manual_only_authentication(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post_json(url: str, payload: dict[str, object], *, timeout: float):
        captured["endpoint"] = url
        captured.update(payload)
        return {"status": "manual_required"}

    monkeypatch.setattr(taobao_login_health, "post_json", _fake_post_json)

    result = taobao_login_health.report_captcha_via_api(
        "http://collector.local/api",
        "http://127.0.0.1:9225",
        "https://sf-item.taobao.com/sf_item/3001.htm",
        manual_only=True,
    )

    assert result == {"status": "manual_required"}
    assert captured["endpoint"] == "http://collector.local/api/report_manual_captcha"
    assert captured["manual_only"] is True

def test_report_captcha_via_api_returns_request_failed_on_transport_error(monkeypatch) -> None:
    monkeypatch.setattr(
        taobao_login_health,
        "post_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("connection reset by peer")),
    )

    result = taobao_login_health.report_captcha_via_api(
        "http://collector.local/api",
        "http://127.0.0.1:9225",
        "https://sf-item.taobao.com/sf_item/3001.htm",
    )

    assert result["status"] == "request_failed"
    assert result["error"] == "OSError: io_error"

def test_report_captcha_via_api_normalizes_non_mapping_response(monkeypatch) -> None:
    monkeypatch.setattr(
        taobao_login_health,
        "post_json",
        lambda *_args, **_kwargs: ["queued"],
    )

    result = taobao_login_health.report_captcha_via_api(
        "http://collector.local/api",
        "http://127.0.0.1:9225",
        "https://sf-item.taobao.com/sf_item/3001.htm",
    )

    assert result == {"status": "unknown_response", "raw": ["queued"]}

def test_read_page_content_with_retries_waits_for_navigation_to_settle() -> None:
    events: list[str] = []

    class FakePage:
        def __init__(self) -> None:
            self.calls = 0

        def content(self) -> str:
            self.calls += 1
            events.append(f"content:{self.calls}")
            if self.calls == 1:
                raise RuntimeError("Page.content: page is navigating")
            return "<html>ok</html>"

        def wait_for_timeout(self, timeout: int) -> None:
            events.append(f"wait:{timeout}")

    html = taobao_login_health.read_page_content_with_retries(FakePage(), attempts=3, wait_timeout_ms=250)

    assert html == "<html>ok</html>"
    assert events == ["content:1", "wait:250", "content:2"]

def test_evaluate_cdp_expression_applies_websocket_timeout_and_closes_socket(monkeypatch) -> None:
    events: list[object] = []

    class FakeWebSocket:
        def settimeout(self, timeout: int) -> None:
            events.append(("settimeout", timeout))

        def send(self, payload: str) -> None:
            events.append(("send", json.loads(payload)["id"]))

        def recv(self) -> str:
            raise taobao_login_health.websocket.WebSocketTimeoutException("stale target")

        def close(self) -> None:
            events.append("close")

    def _fake_create_connection(url: str, **kwargs):
        events.append(("connect", url, kwargs.get("timeout")))
        return FakeWebSocket()

    monkeypatch.setattr(taobao_login_health.websocket, "create_connection", _fake_create_connection)

    try:
        taobao_login_health.evaluate_cdp_expression(
            "ws://127.0.0.1:9223/devtools/page/test",
            "(() => true)()",
        )
    except taobao_login_health.websocket.WebSocketTimeoutException as exc:
        assert "stale target" in str(exc)
    else:
        raise AssertionError("expected websocket timeout to propagate")

    assert events[0] == ("connect", "ws://127.0.0.1:9223/devtools/page/test", 20)
    assert ("settimeout", 20) in events
    assert ("send", 1) in events
    assert events[-1] == "close"

def test_read_cdp_json_rewrites_loopback_websockets_to_remote_endpoint(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def read() -> bytes:
            return json.dumps(
                [
                    {
                        "id": "page-1",
                        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/page-1",
                    }
                ]
            ).encode("utf-8")

    monkeypatch.setattr(taobao_login_health, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    assert taobao_login_health.read_cdp_json(
        "http://192.168.15.104:9224",
        "/json/list",
    ) == [
        {
            "id": "page-1",
            "webSocketDebuggerUrl": "ws://192.168.15.104:9224/devtools/page/page-1",
        }
    ]

def test_classify_healthy_list_payload_when_payload_is_present() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html><script>sf-item-list-data</script></html>",
        final_url="https://sf.taobao.com/list/50025969__2.htm",
        list_summary={
            "body_has_login": False,
            "body_has_punish": False,
            "body_has_challenge": False,
            "body_has_captcha": False,
        },
        payload_present=True,
    )

    assert result["status"] == "healthy_list_payload"
    assert result["healthy"] is True
    assert result["action"] == "none"

def test_classify_valid_payload_ignores_generic_captcha_copy_in_normal_page_html() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html><script>sf-item-list-data</script><div hidden>captcha 验证码 challenge</div></html>",
        final_url="https://sf.taobao.com/list/50025969__2.htm",
        list_summary={
            "body_has_login": False,
            "body_has_punish": False,
            "body_has_challenge": False,
            "body_has_captcha": False,
        },
        payload_present=True,
    )

    assert result["status"] == "healthy_list_payload"
    assert result["healthy"] is True

def test_classify_login_required_from_login_url() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html>淘宝登录</html>",
        final_url="https://login.taobao.com/member/login.jhtml",
        list_summary={
            "body_has_login": True,
            "body_has_punish": False,
            "body_has_challenge": False,
            "body_has_captcha": False,
        },
        payload_present=False,
    )

    assert result["status"] == "login_required"
    assert result["healthy"] is False
    assert result["action"] == "complete_taobao_login"

def test_classify_login_required_from_mobile_or_havana_login_urls() -> None:
    for url in (
        "https://login.m.taobao.com/login.htm?redirect=https://sf.taobao.com/list/page=1",
        "https://login.taobao.com/havanaone/login/login.htm?redirect=https://sf.taobao.com/list/page=1",
    ):
        result = taobao_login_health.classify_taobao_health(
            "<html>淘宝登录</html>",
            final_url=url,
            list_summary={},
            payload_present=False,
        )

        assert result["status"] == "login_required"
        assert result["healthy"] is False
        assert result["action"] == "complete_taobao_login"

def test_classify_captcha_page_from_body_marker_without_payload() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html><body>请先完成验证码</body></html>",
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=6",
        list_summary={},
        payload_present=False,
    )

    assert result["status"] == "captcha_page"
    assert result["healthy"] is False
    assert result["action"] == "complete_taobao_security_verification"

def test_classify_punish_page_from_punish_markers() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html>_____tmd_____/punish x5secdata=</html>",
        final_url="https://market.m.taobao.com/app/msd/m-void/_____tmd_____/punish",
        list_summary={
            "body_has_login": False,
            "body_has_punish": True,
            "body_has_challenge": True,
            "body_has_captcha": False,
        },
        payload_present=False,
    )

    assert result["status"] == "punish_page"
    assert result["healthy"] is False
    assert result["action"] == "complete_taobao_security_verification"

def test_classify_punish_page_precedes_captcha_and_login_markers() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html>_____tmd_____/punish x5secdata= 验证码 淘宝登录</html>",
        final_url="https://market.m.taobao.com/app/msd/m-void/_____tmd_____/punish",
        list_summary={
            "body_has_login": True,
            "body_has_punish": True,
            "body_has_challenge": True,
            "body_has_captcha": True,
        },
        payload_present=False,
    )

    assert result["status"] == "punish_page"
    assert result["healthy"] is False
    assert result["action"] == "complete_taobao_security_verification"

def test_classify_challenge_required_when_body_contains_anti_bot_without_payload() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html><body>anti-bot challenge</body></html>",
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=7",
        list_summary={},
        payload_present=False,
    )

    assert result["status"] == "challenge_required"
    assert result["healthy"] is False
    assert result["action"] == "complete_taobao_security_verification"

def test_classify_challenge_required_from_challenge_url_even_with_payload() -> None:
    result = taobao_login_health.classify_taobao_health(
        '<html><script id="sf-item-list-data" type="application/json">{"data":[{"id":"1001"}]}</script></html>',
        final_url="https://contest.local/challenge?ticket=abc",
        list_summary={
            "body_has_login": False,
            "body_has_punish": False,
            "body_has_challenge": False,
            "body_has_captcha": False,
        },
        payload_present=True,
    )

    assert result["status"] == "challenge_required"
    assert result["healthy"] is False
    assert result["action"] == "complete_taobao_security_verification"

def test_classify_unknown_blocked_when_page_has_no_known_markers_or_payload() -> None:
    result = taobao_login_health.classify_taobao_health(
        "<html><body>unexpected interstitial</body></html>",
        final_url="https://sf.taobao.com/list/50025969__2.htm?page=8",
        list_summary={},
        payload_present=False,
    )

    assert result["status"] == "unknown_blocked"
    assert result["healthy"] is False
    assert result["action"] == "inspect_taobao_session"

def test_operator_hint_points_to_safe_helper_without_cookie_values() -> None:
    hint = taobao_login_health.build_operator_hint(
        status="punish_page",
        cdp_endpoint="http://192.168.65.254:9223",
        check_url="https://sf.taobao.com/list/50025969__2.htm",
    )

    rendered = json.dumps(hint, ensure_ascii=False)
    assert hint["required"] is True
    assert "tools\\taobao_login_health.py" in hint["helper_command"]
    assert "--open-login" in hint["helper_command"]
    assert "--trigger-captcha-solver" not in hint["helper_command"]
    assert "--trigger-captcha-solver" not in hint["host_helper_command"]
    assert "--wait-seconds 180" in hint["helper_command"]
    assert "192.168.65.254:9223" in hint["helper_command"]
    assert "127.0.0.1:9223" in hint["host_helper_command"]
    assert "cookie2=" not in rendered
    assert "sgcookie=" not in rendered
    assert "_tb_token_=" not in rendered

def test_build_cdp_verification_page_matcher_requires_worker_master_marker() -> None:
    matcher = taobao_login_health.build_cdp_verification_page_matcher(
        "https://sf.taobao.com/?__captcha_worker_master=1"
    )

    assert matcher("https://sf.taobao.com/?foo=1&__captcha_worker_master=1") is True
    assert matcher("https://contest.local/auth?__captcha_solver_bg=1") is False
    assert (
        matcher(
            "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?x5secdata=abc"
        )
        is False
    )

def test_build_cdp_verification_page_matcher_reuses_matching_punish_redirect() -> None:
    matcher = taobao_login_health.build_cdp_verification_page_matcher(
        "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"
    )

    assert (
        matcher(
            "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish"
            "?x5secdata=secret&x5step=1"
        )
        is True
    )
    # List challenges share one scope even when the source page/job changes.
    assert matcher(
        "https://sf.taobao.com//list/200782003__1.htm/_____tmd_____/punish"
        "?x5secdata=secret&x5step=1"
    ) is True
    detail_matcher = taobao_login_health.build_cdp_verification_page_matcher(
        "https://sf-item.taobao.com/sf_item/570192626894.htm?__captcha_solver_bg=1"
    )
    assert detail_matcher(
        "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish"
        "?x5secdata=secret&x5step=1"
    ) is False
