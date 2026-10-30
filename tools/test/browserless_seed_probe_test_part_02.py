from __future__ import annotations

from tools.test.browserless_seed_probe_test_context import *


def test_resolve_cdp_endpoint_ignores_read_only_cache(monkeypatch, tmp_path) -> None:
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

        @staticmethod
        def get(_url: str, *, timeout: int) -> _Response:
            assert timeout == 10
            return _Response()

        def close(self) -> None:
            self.close_calls += 1

    def fail_write(*_args, **_kwargs) -> int:
        raise OSError(30, "Read-only file system")

    monkeypatch.setenv(
        "FAPAI_CDP_WEBSOCKET_CACHE_PATH",
        str(tmp_path / "readonly" / "cdp-websocket-cache.json"),
    )
    session = _Session()
    monkeypatch.setattr(browserless_seed_probe.requests, "Session", lambda: session)
    monkeypatch.setattr(Path, "write_text", fail_write)

    assert browserless_seed_probe._resolve_cdp_endpoint(
        "http://pc2-browser-solver:9224"
    ) == "ws://pc2-browser-solver:9224/devtools/browser/browser-remote"
    assert session.close_calls == 1


def test_export_cdp_cookies_websocket_probe_falls_back_to_json_target_list(monkeypatch):
    calls: list[str] = []

    class _Response:
        def __init__(self, payload: object):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self._payload

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True
            self.close_calls = 0

        def get(self, url: str, *, timeout: int):
            calls.append(url)
            if url.endswith("/json/version"):
                raise TimeoutError("version endpoint stalled")
            if url.endswith("/json"):
                return _Response(
                    [
                        {
                            "id": "page-1",
                            "type": "page",
                            "url": "https://sf.taobao.com/list/demo",
                            "webSocketDebuggerUrl": "ws://127.0.0.1:9224/devtools/page/page-1",
                        }
                    ]
                )
            raise AssertionError(url)

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
        "http://127.0.0.1:9224/json/version",
        "http://127.0.0.1:9224/json",
    ]


def test_export_cdp_cookies_websocket_probe_uses_cached_websocket_when_http_endpoints_fail(monkeypatch, tmp_path):
    cache_path = tmp_path / "cdp-websocket-cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "http://127.0.0.1:9224": "ws://127.0.0.1:9224/devtools/browser/browser-cache",
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True
            self.close_calls = 0

        def get(self, url: str, *, timeout: int):
            calls.append(url)
            raise TimeoutError("cdp endpoint stalled")

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

    monkeypatch.setenv("FAPAI_CDP_WEBSOCKET_CACHE_PATH", str(cache_path))
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
        "http://127.0.0.1:9224/json/version",
        "http://127.0.0.1:9224/json",
    ]


def test_resolve_cdp_endpoint_uses_cached_websocket_when_http_probe_fails(monkeypatch, tmp_path):
    cache_path = tmp_path / "cdp-websocket-cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "http://127.0.0.1:9224": "ws://127.0.0.1:9224/devtools/browser/browser-cache",
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True
            self.close_calls = 0

        def get(self, url: str, *, timeout: int):
            calls.append(url)
            raise TimeoutError("cdp endpoint stalled")

        def close(self) -> None:
            self.close_calls += 1

    monkeypatch.setenv("FAPAI_CDP_WEBSOCKET_CACHE_PATH", str(cache_path))
    session = _Session()
    monkeypatch.setattr(browserless_seed_probe.requests, "Session", lambda: session)

    endpoint = browserless_seed_probe._resolve_cdp_endpoint("http://127.0.0.1:9224")

    assert endpoint == "ws://127.0.0.1:9224/devtools/browser/browser-cache"
    assert calls == ["http://127.0.0.1:9224/json/version"]
    assert session.close_calls == 1


def test_probe_seed_page_includes_response_status_and_final_url():
    fake_session = _FakeSession(
        _FakeResponse(
            status_code=200,
            url="https://sf.taobao.com/list/50025969__2.htm?page=1",
            text=LIVE_LIKE_LIST_HTML,
        )
    )

    summary = browserless_seed_probe.probe_seed_page(
        "https://sf.taobao.com/list/50025969__2.htm?page=1",
        cookies=[],
        session=fake_session,
    )

    assert summary["status"] == 200
    assert summary["final_url"] == "https://sf.taobao.com/list/50025969__2.htm?page=1"
    assert summary["item_count"] == 2
    assert len(fake_session.calls) == 1
    assert fake_session.calls[0]["allow_redirects"] is True
    assert "Mozilla/5.0" in fake_session.calls[0]["headers"]["User-Agent"]
    assert fake_session.calls[0]["headers"]["Accept"].startswith("text/html")
    assert fake_session.calls[0]["headers"]["Sec-Fetch-Mode"] == "navigate"
    assert fake_session.calls[0]["headers"]["Sec-Fetch-Site"] == "same-origin"
    assert fake_session.calls[0]["headers"]["Upgrade-Insecure-Requests"] == "1"


def test_build_userscript_like_batch_payload_matches_current_collection_contract_shape():
    payload = browserless_seed_probe.build_userscript_like_batch_payload(
        RAW_LIST_PAYLOAD,
        source_page_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    assert payload["source_page_url"] == "https://sf.taobao.com/list/50025969__2.htm?page=1"
    assert payload["raw_payload"] == RAW_LIST_PAYLOAD["data"]
    assert len(payload["items"]) == 1
    assert payload["items"][0] == {
        "id": 747988656830,
        "title": "测试法拍房 A",
        "currentPrice": 1234567,
        "initialPrice": 1000000,
        "auction_date": "2026-05-18 10:00:00",
        "auction_start_time": "2026-05-17 10:00:00",
        "end": "2026-05-18 10:00:00",
        "url": "https://sf-item.taobao.com/sf_item/747988656830.htm?track_id=demo-1",
        "status": "done",
        "bidCount": 2,
        "bidderCount": 1,
        "applyCount": 1,
        "watchCount": 10,
        "remindCount": 5,
        "viewCount": 30,
        "location": "浙江省杭州市西湖区测试小区 1 幢 2 单元 301 室",
        "full_address": "浙江省杭州市西湖区测试小区 1 幢 2 单元 301 室",
        "district": "西湖区",
        "city": "杭州市",
        "latitude": 30.27,
        "longitude": 120.15,
        "coordinate_source": "list",
        "auction_round": "一拍",
        "housing_type": "住宅",
        "deposit": 100000,
        "is_processed": False,
    }


def test_build_userscript_like_batch_payload_formats_epoch_milliseconds_like_userscript():
    payload = browserless_seed_probe.build_userscript_like_batch_payload(
        {
            "data": [
                {
                    "id": 1,
                    "title": "毫秒时间戳测试",
                    "currentPrice": 1,
                    "initialPrice": 1,
                    "end": 1702453541000,
                    "startTime": 1702346400000,
                    "itemUrl": "//sf-item.taobao.com/sf_item/1.htm",
                    "status": "done",
                    "bidCount": 1,
                }
            ]
        },
        source_page_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    first_item = payload["items"][0]
    assert first_item["auction_date"] == datetime.fromtimestamp(1702453541000 / 1000).strftime("%Y-%m-%d %H:%M:%S")
    assert first_item["auction_start_time"] == datetime.fromtimestamp(1702346400000 / 1000).strftime("%Y-%m-%d %H:%M:%S")


def test_build_userscript_like_batch_payload_normalizes_duplicate_detail_path_slashes():
    payload = browserless_seed_probe.build_userscript_like_batch_payload(
        {
            "data": [
                {
                    "id": 570192626894,
                    "itemUrl": "//sf-item.taobao.com//sf_item/570192626894.htm?track_id=test",
                    "status": "done",
                    "bidCount": 1,
                }
            ]
        },
        source_page_url="https://sf.taobao.com/list/50025969__2.htm?page=1",
    )

    assert payload["items"][0]["url"] == (
        "https://sf-item.taobao.com/sf_item/570192626894.htm?track_id=test"
    )


def test_write_cookie_snapshot_persists_json_payload(tmp_path: Path):
    output_path = tmp_path / "cookies.json"
    cookies = [{"name": "cookie2", "value": "abc"}]

    browserless_seed_probe.write_cookie_snapshot(cookies, output_path)

    assert json.loads(output_path.read_text(encoding="utf-8")) == cookies


def test_load_cookie_snapshot_reads_json_payload_from_disk(tmp_path: Path):
    output_path = tmp_path / "cookies.json"
    cookies = [
        {"name": "cookie2", "value": "abc", "domain": ".taobao.com"},
        {"name": "_tb_token_", "value": "xyz", "domain": "login.taobao.com"},
    ]
    output_path.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")

    loaded = browserless_seed_probe.load_cookie_snapshot(output_path)

    assert loaded == cookies


def test_summarize_cookie_snapshot_reports_safe_metadata_without_cookie_values():
    summary = browserless_seed_probe.summarize_cookie_snapshot(
        [
            {
                "name": "cookie2",
                "value": "abc",
                "domain": ".taobao.com",
                "secure": True,
                "httpOnly": False,
                "expires": 1893456000,
            },
            {
                "name": "_tb_token_",
                "value": "xyz",
                "domain": "login.taobao.com",
                "secure": False,
                "httpOnly": True,
                "expires": -1,
            },
        ]
    )

    assert summary == {
        "count": 2,
        "domains": [".taobao.com", "login.taobao.com"],
        "names": ["_tb_token_", "cookie2"],
        "secure_count": 1,
        "http_only_count": 1,
        "session_count": 1,
        "persistent_count": 1,
        "earliest_expiry": datetime.fromtimestamp(1893456000).strftime("%Y-%m-%d %H:%M:%S"),
        "latest_expiry": datetime.fromtimestamp(1893456000).strftime("%Y-%m-%d %H:%M:%S"),
        "shape_fingerprint": summary["shape_fingerprint"],
        "value_fingerprint": summary["value_fingerprint"],
    }


def test_summarize_cookie_snapshot_stable_shape_fingerprint_changes_only_when_structure_changes():
    base = browserless_seed_probe.summarize_cookie_snapshot(
        [
            {"name": "cookie2", "value": "abc", "domain": ".taobao.com", "secure": True, "httpOnly": False, "expires": 1893456000},
            {"name": "_tb_token_", "value": "xyz", "domain": "login.taobao.com", "secure": False, "httpOnly": True, "expires": -1},
        ]
    )
    same_shape_new_values = browserless_seed_probe.summarize_cookie_snapshot(
        [
            {"name": "cookie2", "value": "new-abc", "domain": ".taobao.com", "secure": True, "httpOnly": False, "expires": 1893456000},
            {"name": "_tb_token_", "value": "new-xyz", "domain": "login.taobao.com", "secure": False, "httpOnly": True, "expires": -1},
        ]
    )
    changed_shape = browserless_seed_probe.summarize_cookie_snapshot(
        [
            {"name": "cookie2", "value": "abc", "domain": ".taobao.com", "secure": True, "httpOnly": False, "expires": 1893456000},
        ]
    )

    assert base["shape_fingerprint"] == same_shape_new_values["shape_fingerprint"]
    assert base["value_fingerprint"] != same_shape_new_values["value_fingerprint"]
    assert base["shape_fingerprint"] != changed_shape["shape_fingerprint"]


def test_diff_cookie_snapshots_reports_added_and_removed_cookie_keys_safely():
    diff = browserless_seed_probe.diff_cookie_snapshots(
        [
            {"name": "cookie2", "value": "abc", "domain": ".taobao.com", "path": "/"},
            {"name": "_tb_token_", "value": "xyz", "domain": ".taobao.com", "path": "/"},
        ],
        [
            {"name": "cookie2", "value": "abc-2", "domain": ".taobao.com", "path": "/"},
            {"name": "XSRF-TOKEN", "value": "token", "domain": "login.taobao.com", "path": "/"},
        ],
    )

    assert diff["added_domains"] == ["login.taobao.com"]
    assert diff["removed_domains"] == []
    assert diff["added_names"] == ["XSRF-TOKEN"]
    assert diff["removed_names"] == ["_tb_token_"]
    assert diff["added_keys"] == ["XSRF-TOKEN|login.taobao.com|/"]
    assert diff["removed_keys"] == ["_tb_token_|.taobao.com|/"]
    assert diff["shared_key_count"] == 1
    assert diff["shape_fingerprint_equal"] is False
    assert diff["value_fingerprint_equal"] is False
