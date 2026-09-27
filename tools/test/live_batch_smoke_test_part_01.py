from src import llm_openai_compatible
from tools.test.live_batch_smoke_test_context import *  # noqa: F401,F403


def test_preflight_llm_backend_passes_chat_probe_flag(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def _preflight_llm_backend(timeout: float, *, check_chat: bool = False) -> dict[str, object]:
        calls.append({"timeout": timeout, "check_chat": check_chat})
        return {"enabled": True}

    monkeypatch.setattr(llm_helper, "preflight_llm_backend", _preflight_llm_backend)

    result = live_batch_smoke.preflight_llm_backend(timeout=3.5, check_chat=True)

    assert result == {"enabled": True}
    assert calls == [{"timeout": 3.5, "check_chat": True}]

def test_preflight_llm_backend_skips_models_already_disabled_by_auth_failures(monkeypatch) -> None:
    pool = [
        {"name": "model-a", "app_id": "a", "api_key": "ak", "api_secret": "as", "ws_url": "wss://unit.test/a", "model_id": "mid-a", "max_concurrent": 1},
        {"name": "model-b", "app_id": "b", "api_key": "bk", "api_secret": "bs", "ws_url": "wss://unit.test/b", "model_id": "mid-b", "max_concurrent": 1},
    ]
    selector = llm_helper.ModelSelector(pool)
    monkeypatch.setattr(llm_openai_compatible, "get_model_pool", lambda: pool)
    monkeypatch.setattr(llm_openai_compatible, "get_model_selector", lambda: selector)
    monkeypatch.setattr(llm_openai_compatible, "_get_openai_compatible_config", lambda: None)

    calls = {"count": 0}

    def _fake_get_response(self, _prompt):
        calls["count"] += 1
        self.error_code = 11200
        self.error_msg = "AppIdNoAuthError"
        selector.disable_model(
            self.model_config["name"],
            "error_code=11200, error_msg=AppIdNoAuthError",
        )
        return ""

    monkeypatch.setattr(llm_helper.AIService, "get_response", _fake_get_response)

    first = llm_helper.preflight_llm_backend(timeout=1.0, check_chat=True)
    second = llm_helper.preflight_llm_backend(timeout=1.0, check_chat=True)

    assert first["chat_status_code"] == 401
    assert second["chat_status_code"] == 401
    assert calls["count"] == len(pool)


def test_process_item_raw_only_writes_raw_artifacts_without_llm(tmp_path: Path, monkeypatch) -> None:
    html = '<html><script>var description-data = {"area":"88.8㎡"};</script>建筑面积88.8平方米</html>'
    seed = {
        "id": "raw-1001",
        "title": "原始详情测试",
        "url": "https://sf-item.taobao.com/sf_item/raw-1001.htm",
        "source_page_url": "https://sf.taobao.com/list/page",
    }

    def _fetch_detail_html(*_args, **_kwargs):
        return html, seed["url"], len(html.encode("utf-8")), "unit-test"

    def _extract_auction_data(*_args, **_kwargs):
        raise AssertionError("raw-only detail capture must not call the LLM extractor")

    monkeypatch.setattr(live_batch_smoke, "fetch_detail_html", _fetch_detail_html)
    monkeypatch.setattr(llm_helper, "extract_auction_data", _extract_auction_data)

    selected = live_batch_smoke.process_item(
        object(),
        seed,
        {},
        config=live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            raw_only=True,
        ),
    )

    item_dir = tmp_path / "raw-1001"
    assert selected["item_id"] == "raw-1001"
    assert selected["detail_capture_mode"] == "raw"
    assert selected["fetch"]["detail_final_url"] == seed["url"]
    assert (item_dir / "seed.json").exists()
    assert (item_dir / "detail.html").read_text(encoding="utf-8") == html
    assert (item_dir / "description-data.json").exists()
    assert (item_dir / "selected.json").exists()
    assert not (item_dir / "extracted.json").exists()
    assert not (item_dir / "final.json").exists()

def test_analyze_raw_item_reads_artifacts_and_writes_ai_outputs(tmp_path: Path, monkeypatch) -> None:
    item_id = "raw-2001"
    item_dir = tmp_path / item_id
    item_dir.mkdir()
    seed = {
        "id": item_id,
        "title": "广州市南沙区测试小区1号101房",
        "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
        "currentPrice": 1230000,
        "initialPrice": 1000000,
        "auction_date": "2026-01-01 10:00:00",
        "bidCount": 4,
        "applyCount": 2,
    }
    html = """
    <html>
      <body>
        <input id="J_StartPrice" value="1000000.00" />
        <div id="itemAddress">广东省 广州市 南沙区</div>
        <div id="itemAddressDetail">测试小区1号101房</div>
        广州市南沙区测试小区1号101房，建筑面积88.8平方米
      </body>
    </html>
    """
    live_batch_smoke.write_json(item_dir / "seed.json", seed)
    (item_dir / "detail.html").write_text(html, encoding="utf-8")
    live_batch_smoke.write_json(item_dir / "description-data.json", {"area_sqm": 88.8, "text_len": 20, "has_area_marker": True})
    (item_dir / "description-data.txt").write_text(
        "拍卖标的调查情况表\n面积：88.8平方米，起拍价：1000000元。",
        encoding="utf-8",
    )
    live_batch_smoke.write_json(
        item_dir / "selected.json",
        {
            "item_id": item_id,
            "detail_capture_mode": "raw",
            "fetch": {
                "method": "http_cookie",
                "detail_final_url": seed["url"],
                "detail_html_bytes": len(html.encode("utf-8")),
            },
            "trusted_seed": {
                "title": seed["title"],
                "currentPrice": seed["currentPrice"],
                "initialPrice": seed["initialPrice"],
                "auction_date": seed["auction_date"],
                "bidCount": seed["bidCount"],
                "applyCount": seed["applyCount"],
            },
        },
    )

    def _extract_auction_data(content: str, item_id: str | None = None) -> str:
        assert "【可信种子】" in content
        assert "currentPrice: 1230000" in content
        assert "拍卖标的调查情况表" in content
        assert "<html>" not in content
        return json.dumps(
            {
                "标题": "AI 标题",
                "完整地址": "广州市南沙区测试小区1号101房",
                "城市": "广州市",
                "区": "南沙区",
                "所属小区": "测试小区",
                "建筑面积": 88.8,
                "成交价格": 1230000,
                "起拍价格": 1000000,
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(llm_helper, "extract_auction_data", _extract_auction_data)

    selected = live_batch_smoke.analyze_raw_item(
        item_id,
        output_dir=tmp_path,
        do_risk=False,
    )

    assert selected["item_id"] == item_id
    assert selected["fetch"]["method"] == "http_cookie"
    assert selected["auction_and_property"]["area_sqm"] == 88.8
    assert (item_dir / "extracted.json").exists()
    assert (item_dir / "final.json").exists()
    final_item = live_batch_smoke.load_json(item_dir / "final.json")
    assert final_item["detail_captured"] is True
    assert final_item["is_processed"] is True

def test_build_detail_analysis_input_prefers_compact_summary_and_redacts_contacts(tmp_path: Path) -> None:
    item_id = "raw-compact-2002"
    item_dir = tmp_path / item_id
    item_dir.mkdir()
    seed = {
        "id": item_id,
        "title": "广州市南沙区测试小区1号101房",
        "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
        "currentPrice": 1230000,
        "initialPrice": 1000000,
        "auction_date": "2026-01-01 10:00:00",
        "bidCount": 4,
        "applyCount": 2,
        "status": "done",
    }
    html = """
    <html>
      <head><title>广州市南沙区测试小区1号101房 - 司法拍卖</title></head>
      <body>
        <span class="countdown J_TimeLeft">2026/01/01 10:05:55</span>
        <input id="J_StartPrice" value="900000.00" />
        <div id="itemAddress">广东省 广州市 南沙区</div>
        <div id="itemAddressDetail">测试小区1号101房</div>
        联系方式：张先生 手机：13231377737
      </body>
    </html>
    """
    (item_dir / "description-data.txt").write_text(
        "拍卖标的调查情况表\n面积：88.8平方米，起拍价：900000元，保证金50000元。",
        encoding="utf-8",
    )

    effective_seed, analysis_text = live_batch_smoke._build_detail_analysis_input(
        item_id=item_id,
        item_dir=item_dir,
        seed=seed,
        html=html,
        selected={
            "fetch": {"detail_final_url": seed["url"]},
            "trusted_seed": {"title": seed["title"], "currentPrice": seed["currentPrice"]},
        },
        description_data={"text_path": str(item_dir / "description-data.txt")},
    )

    assert effective_seed["initialPrice"] == 900000.0
    assert "13231377737" not in analysis_text
    assert "张先生" not in analysis_text
    assert "currentPrice: 1230000" in analysis_text
    assert "起拍价_html: 900000.0" in analysis_text
    assert "拍卖标的调查情况表" in analysis_text

def test_compute_area_stats_counts_missing_and_description_fallbacks() -> None:
    results = [
        _result("has-area", area_sqm=117.06, unit_price=115792.59, desc_area=117.06),
        _result("missing-area", area_sqm=None, unit_price=0, desc_area=None),
    ]

    stats = live_batch_smoke.compute_area_stats(results)

    assert stats == {
        "total": 2,
        "area_present_count": 1,
        "area_missing_count": 1,
        "unit_price_present_count": 1,
        "unit_price_missing_count": 1,
        "description_area_present_count": 1,
        "description_area_missing_count": 1,
        "area_present_ratio": 0.5,
    }

def test_build_http_can_use_explicit_fapai_proxy(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_HTTP_PROXY", "http://proxy.local:3128")
    monkeypatch.setenv("FAPAI_HTTPS_PROXY", "http://proxy.local:3128")

    session = live_batch_smoke.build_http([])

    assert session.trust_env is False
    assert session.proxies == {
        "http": "http://proxy.local:3128",
        "https": "http://proxy.local:3128",
    }

def test_build_http_ignores_generic_proxy_env(monkeypatch) -> None:
    monkeypatch.delenv("FAPAI_HTTP_PROXY", raising=False)
    monkeypatch.delenv("FAPAI_HTTPS_PROXY", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://generic-proxy.local:3128")

    session = live_batch_smoke.build_http([])

    assert session.trust_env is False
    assert session.proxies == {"http": None, "https": None}

def test_parse_csv_values_deduplicates_semicolon_and_whitespace() -> None:
    values = live_batch_smoke.parse_csv_values(" 2;1,2,, 3 ;1 ")

    assert values == ("2", "1", "3")

def test_export_cookies_falls_back_to_snapshot_when_live_cdp_export_fails(monkeypatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "taobao-cookies.json"
    calls: list[tuple[str, object]] = []

    class _FakeProbe:
        @staticmethod
        def export_cdp_cookies(endpoint: str):
            calls.append(("export", endpoint))
            raise RuntimeError("cdp unavailable")

        @staticmethod
        def load_cookie_snapshot(path: Path):
            calls.append(("snapshot", path))
            return [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))

    cookies = live_batch_smoke.export_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]
    assert calls == [
        ("export", "http://127.0.0.1:9223"),
        ("snapshot", snapshot_path),
    ]

def test_export_cookies_uses_node_snapshot_path_when_explicit_snapshot_env_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    shared_root = tmp_path
    expected_snapshot_path = shared_root / "secrets" / "nodes" / "pc2" / "taobao-cookies.json"
    calls: list[tuple[str, object]] = []

    class _FakeProbe:
        @staticmethod
        def export_cdp_cookies(endpoint: str):
            calls.append(("export", endpoint))
            raise RuntimeError("cdp unavailable")

        @staticmethod
        def load_cookie_snapshot(path: Path):
            calls.append(("snapshot", path))
            return [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.delenv("FAPAI_COOKIE_SNAPSHOT", raising=False)
    monkeypatch.setenv("FAPAI_SHARED_DATA_ROOT_HOST", str(shared_root))
    monkeypatch.setenv("FAPAI_NODE_ID", "pc2")

    cookies = live_batch_smoke.export_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]
    assert calls == [
        ("export", "http://127.0.0.1:9223"),
        ("snapshot", expected_snapshot_path),
    ]

def test_export_cookies_writes_snapshot_after_live_cdp_export(monkeypatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "taobao-cookies.json"
    live_cookies = [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]
    calls: list[tuple[str, object]] = []

    class _FakeProbe:
        @staticmethod
        def export_cdp_cookies(endpoint: str):
            calls.append(("export", endpoint))
            return live_cookies

        @staticmethod
        def write_cookie_snapshot(cookies: object, path: Path):
            calls.append(("write", path, cookies))

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))

    cookies = live_batch_smoke.export_cookies("http://127.0.0.1:9223")

    assert cookies == live_cookies
    assert calls == [
        ("export", "http://127.0.0.1:9223"),
        ("write", snapshot_path, live_cookies),
    ]

def test_export_cookies_can_prefer_verified_snapshot_without_live_cdp(monkeypatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "taobao-cookies.json"
    calls: list[tuple[str, object]] = []

    class _FakeProbe:
        @staticmethod
        def export_cdp_cookies(endpoint: str):
            calls.append(("export", endpoint))
            raise AssertionError("live CDP export should not be used")

        @staticmethod
        def load_cookie_snapshot(path: Path):
            calls.append(("snapshot", path))
            return [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT_PREFER", "1")

    cookies = live_batch_smoke.export_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "cookie2", "value": "abc", "domain": ".taobao.com"}]
    assert calls == [("snapshot", snapshot_path)]

def test_export_cookies_falls_back_to_live_cdp_when_preferred_snapshot_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "missing-taobao-cookies.json"
    calls: list[tuple[str, object]] = []

    class _FakeProbe:
        @staticmethod
        def export_cdp_cookies(endpoint: str):
            calls.append(("export", endpoint))
            return [{"name": "live-cookie", "value": "abc", "domain": ".taobao.com"}]

        @staticmethod
        def load_cookie_snapshot(path: Path):
            calls.append(("snapshot", path))
            raise FileNotFoundError(path)

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT_PREFER", "1")

    cookies = live_batch_smoke.export_cookies("http://127.0.0.1:9223")

    assert cookies == [{"name": "live-cookie", "value": "abc", "domain": ".taobao.com"}]
    assert calls == [
        ("snapshot", snapshot_path),
        ("export", "http://127.0.0.1:9223"),
    ]

def test_export_cookies_raises_combined_error_when_cdp_and_snapshot_both_fail(monkeypatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "taobao-cookies.json"

    class _FakeProbe:
        @staticmethod
        def export_cdp_cookies(_endpoint: str):
            raise RuntimeError("cdp unavailable")

        @staticmethod
        def load_cookie_snapshot(_path: Path):
            raise FileNotFoundError("snapshot missing")

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))

    with pytest.raises(RuntimeError, match="snapshot fallback failed"):
        live_batch_smoke.export_cookies("http://127.0.0.1:9223")
