from tools.test.live_batch_smoke_test_context import *  # noqa: F401,F403


def test_run_live_smoke_marks_failed_item_in_resume_state_and_summary_error(tmp_path: Path, monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "item_count": 1,
                "final_url": final_url,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [
                    {
                        "id": "failed-item",
                        "url": "https://sf-item.taobao.com/sf_item/failed-item.htm",
                        "title": "失败标的",
                    }
                ],
            }

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: ("list", target_url, 200, "http_cookie"),
    )
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(
        live_batch_smoke,
        "process_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("detail pipeline exploded")),
    )
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda _seconds: None)

    resume_state_path = tmp_path / "resume_state.json"
    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page=1",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            resume_state_path=resume_state_path,
            resume_enabled=True,
        )
    )

    assert exit_code == 1
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["attempted_items"] == 1
    assert summary["processed_items"] == 0
    assert summary["error_count"] == 1
    assert summary["errors"][0]["item_id"] == "failed-item"
    assert summary["errors"][0]["error"] == "RuntimeError: runtime_error"
    error_payload = live_batch_smoke.load_json(tmp_path / "failed-item.error.json")
    assert error_payload["item_id"] == "failed-item"
    assert error_payload["error"] == "RuntimeError: runtime_error"
    resume_state = live_batch_smoke.load_resume_state(resume_state_path)
    assert resume_state["items"]["failed-item"]["status"] == "failed"
    assert resume_state["items"]["failed-item"]["attempts"] == 1
    assert resume_state["items"]["failed-item"]["error"] == "RuntimeError: runtime_error"

def test_run_live_smoke_stops_after_target_success_without_processing_remaining_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "item_count": 3,
                "final_url": final_url,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [
                    {"id": "a", "url": "https://sf-item.taobao.com/sf_item/a.htm"},
                    {"id": "b", "url": "https://sf-item.taobao.com/sf_item/b.htm"},
                    {"id": "c", "url": "https://sf-item.taobao.com/sf_item/c.htm"},
                ],
            }

    processed_ids: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        return _result(str(seed["id"]), area_sqm=88.8, unit_price=12345, desc_area=88.8)

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: ("list", target_url, 200, "http_cookie"),
    )
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda _seconds: None)

    resume_state_path = tmp_path / "resume_state.json"
    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page=1",
            target_success=1,
            max_attempts=3,
            do_risk=False,
            resume_state_path=resume_state_path,
            resume_enabled=True,
        )
    )

    assert exit_code == 0
    assert processed_ids == ["a"]
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["attempted_items"] == 1
    assert summary["processed_items"] == 1
    resume_state = live_batch_smoke.load_resume_state(resume_state_path)
    assert live_batch_smoke.is_resume_completed(resume_state, "a") is True
    assert "b" not in resume_state["items"]
    assert "c" not in resume_state["items"]

def test_run_live_smoke_fetches_multiple_sort_pages_before_detail_processing(tmp_path: Path, monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(html: str, *, final_url: str) -> dict[str, object]:
            item_count = 2 if "empty" not in html else 0
            return {"item_count": item_count, "final_url": final_url}

        @staticmethod
        def extract_list_payload(html: str) -> dict[str, object]:
            return {"source": html}

        @staticmethod
        def build_userscript_like_batch_payload(payload, *, source_page_url: str) -> dict[str, object]:
            if "st_param=2" in source_page_url and "page=1" in source_page_url:
                items = [{"id": "time-a"}, {"id": "shared"}]
            elif "st_param=1" in source_page_url and "page=1" in source_page_url:
                items = [{"id": "shared"}, {"id": "price-only"}]
            else:
                items = []
            return {
                "source_page_url": source_page_url,
                "items": items,
            }

    fetched_urls: list[str] = []
    processed_ids: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint, target_url, user_agent):
        fetched_urls.append(target_url)
        html = "empty" if "page=2" in target_url else "list"
        return html, target_url, 200, "http"

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        return _result(str(seed["id"]), area_sqm=88.8, unit_price=12345, desc_area=88.8)

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(live_batch_smoke, "fetch_list_page", _fetch_list_page)
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/50025969__2.htm?location_code=110101&st_param=2&auction_start_seg=-1&page=1",
            target_success=3,
            max_attempts=10,
            do_risk=False,
            resume_state_path=tmp_path / "resume_state.json",
            resume_enabled=True,
            list_st_params=("2", "1"),
            list_location_codes=("110101",),
            list_categories=("50025969",),
            list_max_pages=2,
            list_stop_on_empty=True,
        )
    )

    assert exit_code == 0
    assert len(fetched_urls) == 4
    assert processed_ids == ["time-a", "shared", "price-only"]
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["list_union"]["source_count"] == 4
    assert summary["list_union"]["unique_item_count"] == 3
    assert summary["list_union"]["duplicate_item_count"] == 1

def test_positive_int_rejects_zero_and_negative() -> None:
    assert live_batch_smoke.positive_int("3") == 3

    for raw in ("0", "-2"):
        try:
            live_batch_smoke.positive_int(raw)
        except Exception as exc:
            assert isinstance(exc, live_batch_smoke.argparse.ArgumentTypeError)
            assert str(exc) == "must be >= 1"
        else:
            raise AssertionError(f"expected positive_int({raw!r}) to raise ArgumentTypeError")

def test_run_live_smoke_llm_preflight_failure_aborts_before_detail_items(tmp_path: Path, monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {"item_count": 1, "final_url": final_url}

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {"source_page_url": source_page_url, "items": [{"id": "preflight-blocked"}]}

    class _FakeResponse:
        text = "<html>list</html>"
        url = "https://sf.taobao.com/list/page"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _FakeHttp:
        @staticmethod
        def get(*_args, **_kwargs) -> _FakeResponse:
            return _FakeResponse()

    processed_ids: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        return _result(str(seed["id"]), area_sqm=88.8, unit_price=12345, desc_area=88.8)

    def _preflight_llm_backend(*, timeout: float) -> dict[str, object]:
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: _FakeHttp())
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)
    monkeypatch.setattr(live_batch_smoke, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with pytest.raises(RuntimeError, match="llm unavailable"):
        live_batch_smoke.run_live_smoke(
            live_batch_smoke.LiveSmokeConfig(
                output_dir=tmp_path,
                cdp_endpoint="http://127.0.0.1:9223",
                target_url="https://sf.taobao.com/list/page",
                target_success=1,
                max_attempts=1,
                do_risk=False,
                resume_state_path=tmp_path / "resume_state.json",
                resume_enabled=True,
                llm_preflight_enabled=True,
                llm_preflight_timeout_seconds=3.5,
            )
        )

    assert processed_ids == []
    assert not (tmp_path / "preflight-blocked.error.json").exists()

def test_run_live_smoke_llm_preflight_failure_aborts_before_taobao_network(tmp_path: Path, monkeypatch) -> None:
    def _preflight_llm_backend(*, timeout: float) -> dict[str, object]:
        raise RuntimeError("llm unavailable")

    def _export_cookies(_endpoint: str):
        raise AssertionError("Taobao/CDP should not be touched when LLM preflight already fails")

    monkeypatch.setattr(live_batch_smoke, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", _export_cookies)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with pytest.raises(RuntimeError, match="llm unavailable"):
        live_batch_smoke.run_live_smoke(
            live_batch_smoke.LiveSmokeConfig(
                output_dir=tmp_path,
                cdp_endpoint="http://127.0.0.1:9223",
                target_url="https://sf.taobao.com/list/page",
                target_success=1,
                max_attempts=1,
                do_risk=False,
                llm_preflight_enabled=True,
            )
        )

def test_run_loop_continues_across_batches_with_same_resume_state(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[Path | None, bool]] = []

    def _run_live_smoke(config: live_batch_smoke.LiveSmokeConfig) -> int:
        calls.append((config.resume_state_path, config.resume_enabled))
        return 0

    monkeypatch.setattr(live_batch_smoke, "run_live_smoke", _run_live_smoke)
    summary = live_batch_smoke.run_loop(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=2,
            max_attempts=4,
            do_risk=False,
            resume_state_path=tmp_path / "resume_state.json",
            resume_enabled=True,
        ),
        max_runs=2,
        interval_seconds=0,
    )

    assert summary["run_count"] == 2
    assert summary["exit_codes"] == [0, 0]
    assert calls == [
        (tmp_path / "resume_state.json", True),
        (tmp_path / "resume_state.json", True),
    ]

def test_run_loop_keeps_process_alive_after_transient_batch_error(tmp_path: Path, monkeypatch) -> None:
    calls = 0

    def _run_live_smoke(_config: live_batch_smoke.LiveSmokeConfig) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("cdp temporarily unavailable")
        return 0

    monkeypatch.setattr(live_batch_smoke, "run_live_smoke", _run_live_smoke)

    summary = live_batch_smoke.run_loop(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=2,
            max_attempts=4,
            do_risk=False,
            resume_state_path=tmp_path / "resume_state.json",
            resume_enabled=True,
        ),
        max_runs=2,
        interval_seconds=0,
    )

    assert summary["run_count"] == 2
    assert summary["exit_codes"] == [1, 0]
    assert summary["ok"] is False
    assert len(summary["errors"]) == 1
    assert summary["errors"][0]["error"] == "RuntimeError: runtime_error"
