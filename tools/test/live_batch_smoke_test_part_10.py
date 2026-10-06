from tools.test.live_batch_smoke_test_context import *  # noqa: F401,F403


def _list_collection(items: list[dict[str, str]]) -> dict[str, object]:
    return {
        "items": items,
        "list_union": {"source_count": 1, "unique_item_count": len(items)},
        "first_fetch": {
            "list_status": 200,
            "list_final_url": "https://sf.taobao.com/list/page=1",
            "list_fetch_method": "http_cookie",
            "list_item_count": len(items),
        },
    }


def test_run_live_smoke_stops_detail_batch_after_first_challenge(tmp_path: Path, monkeypatch) -> None:
    processed_ids: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        raise live_batch_smoke.DetailChallengeError(
            "browser detail request",
            "https://sf-item.taobao.com/sf_item/a.htm/_____tmd_____/punish?x5step=1",
        )

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(
        live_batch_smoke,
        "collect_list_union",
        lambda *_args, **_kwargs: _list_collection(
            [
                {"id": "a", "url": "https://sf-item.taobao.com/sf_item/a.htm"},
                {"id": "b", "url": "https://sf-item.taobao.com/sf_item/b.htm"},
            ]
        ),
    )
    monkeypatch.setattr(live_batch_smoke, "load_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", lambda _seconds: None)

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page=1",
            target_success=2,
            max_attempts=2,
            do_risk=False,
            resume_enabled=False,
            challenge_cooldown_seconds=480,
        )
    )

    assert exit_code == 1
    assert processed_ids == ["a"]
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["attempted_items"] == 1
    assert summary["challenge_break"] == {
        "item_id": "a",
        "operation": "browser detail request",
        "retry_after_seconds": 480.0,
    }
    serialized = json.dumps(summary)
    assert "x5secdata" not in serialized
    assert "x5step" not in serialized


def test_run_live_smoke_does_not_start_details_after_list_challenge(tmp_path: Path, monkeypatch) -> None:
    challenge_break = {
        "scope": "list",
        "operation": "list page fetch",
        "retry_after_seconds": 480.0,
    }
    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(
        live_batch_smoke,
        "collect_list_union",
        lambda *_args, **_kwargs: {
            **_list_collection(
                [{"id": "a", "url": "https://sf-item.taobao.com/sf_item/a.htm"}]
            ),
            "challenge_break": challenge_break,
        },
    )
    monkeypatch.setattr(
        live_batch_smoke,
        "load_open_browser_pages",
        lambda _endpoint: (_ for _ in ()).throw(
            AssertionError("detail browser state must not load after a list challenge")
        ),
    )

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page=1",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            resume_enabled=False,
        )
    )

    assert exit_code == 1
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["challenge_break"] == challenge_break
    assert summary["no_candidate_reason"] == "list_challenge_page"


def test_loop_honors_challenge_cooldown_before_next_batch(tmp_path: Path, monkeypatch) -> None:
    sleep_calls: list[float] = []

    def _run_live_smoke(config: live_batch_smoke.LiveSmokeConfig) -> int:
        live_batch_smoke.write_json(
            config.output_dir / "summary.json",
            {"challenge_break": {"item_id": "a"}},
        )
        return 1

    monkeypatch.setattr(live_batch_smoke, "run_live_smoke", _run_live_smoke)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", sleep_calls.append)

    summary = live_batch_smoke.run_loop(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page=1",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            challenge_cooldown_seconds=480,
        ),
        max_runs=2,
        interval_seconds=30,
    )

    assert summary["exit_codes"] == [1, 1]
    assert sleep_calls == [480.0]


def test_list_union_stops_all_sources_after_challenge(monkeypatch) -> None:
    fetch_calls: list[str] = []

    class FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "item_count": 0,
                "final_url": final_url,
                "body_has_challenge": True,
                "body_has_login": False,
                "body_has_punish": True,
            }

        @staticmethod
        def extract_list_payload(_html: str):
            return None

    def _fetch_list_page(_http, *, cdp_endpoint, target_url, user_agent):
        fetch_calls.append(target_url)
        return (
            "<html>captcha challenge</html>",
            f"{target_url}/_____tmd_____/punish?x5step=1",
            200,
            "http_cookie",
        )

    monkeypatch.setattr(live_batch_smoke, "fetch_list_page", _fetch_list_page)
    config = live_batch_smoke.LiveSmokeConfig(
        output_dir=Path("."),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/50025969__2.htm?st_param=2&page=1",
        target_success=1,
        max_attempts=1,
        do_risk=False,
        list_st_params=("2", "1"),
        list_delay_seconds=0,
        challenge_cooldown_seconds=480,
    )

    result = live_batch_smoke.collect_list_union(FakeProbe, object(), config)

    assert len(fetch_calls) == 1
    assert result["items"] == []
    assert result["challenge_break"] == {
        "scope": "list",
        "operation": "list page fetch",
        "retry_after_seconds": 480.0,
    }


def test_list_union_stops_on_challenge_url_even_when_stale_payload_is_parseable(monkeypatch) -> None:
    fetch_calls: list[str] = []

    class FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {"item_count": 1, "final_url": final_url}

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"items": [{"id": "stale"}]}

        @staticmethod
        def build_userscript_like_batch_payload(*_args, **_kwargs):
            raise AssertionError("stale payload from a challenge URL must not be processed")

    def _fetch_list_page(_http, *, cdp_endpoint, target_url, user_agent):
        fetch_calls.append(target_url)
        return (
            "<html><script>stale list payload</script></html>",
            "https://sec.taobao.com/_____tmd_____/punish?x5step=1",
            200,
            "http_cookie",
        )

    monkeypatch.setattr(live_batch_smoke, "fetch_list_page", _fetch_list_page)
    config = live_batch_smoke.LiveSmokeConfig(
        output_dir=Path("."),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/50025969__2.htm?st_param=2&page=1",
        target_success=1,
        max_attempts=1,
        do_risk=False,
        list_st_params=("2", "1"),
        list_delay_seconds=0,
        challenge_cooldown_seconds=480,
    )

    result = live_batch_smoke.collect_list_union(FakeProbe, object(), config)

    assert len(fetch_calls) == 1
    assert result["items"] == []
    assert result["challenge_break"] == {
        "scope": "list",
        "operation": "list page fetch",
        "retry_after_seconds": 480.0,
    }
    source = result["list_union"]["sources"][0]
    assert source["payload_present"] is True
    assert source["error"] == "list challenge URL"
    assert source["list_final_url"] == "https://sec.taobao.com/_____tmd_____/punish"
    serialized = json.dumps(result)
    assert "x5secdata" not in serialized
    assert "x5step" not in serialized


def test_list_challenge_url_detection_ignores_unrelated_query_value() -> None:
    assert not live_batch_smoke._list_final_url_has_challenge(
        "https://sf.taobao.com/list/page=1?campaign=challenge-week"
    )


def test_list_navigation_reuses_challenge_with_reordered_same_job_query(monkeypatch) -> None:
    from tools import taobao_login_health

    challenge_target = {
        "id": "existing-challenge",
        "type": "page",
        "url": (
            "https://sf.taobao.com/list/50025969__2.htm?location_code=310101"
            "&st_param=1&page=4"
        ),
    }
    challenge_page = (
        "<html>_____tmd_____/punish challenge</html>",
        str(challenge_target["url"]),
    )

    monkeypatch.setattr(live_batch_smoke, "_reuse_existing_taobao_login_page", lambda _endpoint: None)
    monkeypatch.setattr(taobao_login_health, "list_cdp_targets", lambda _endpoint: [challenge_target])
    monkeypatch.setattr(
        live_batch_smoke,
        "_read_cdp_list_target_html",
        lambda _endpoint, target: challenge_page if target is challenge_target else None,
    )
    monkeypatch.setattr(
        taobao_login_health,
        "compact_cdp_pages_if_needed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an existing challenge must prevent opening another list target")
        ),
    )
    monkeypatch.setattr(
        taobao_login_health,
        "read_cdp_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an existing challenge must prevent /json/new")
        ),
    )

    result = live_batch_smoke.fetch_browser_navigation_list_page(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/50025969__2.htm?page=4&st_param=1&location_code=310101",
    )

    assert result == challenge_page


def test_list_union_applies_jittered_delay_between_sources(monkeypatch) -> None:
    sleep_calls: list[float] = []

    class FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {"item_count": 1, "final_url": final_url}

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"items": []}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str):
            return {"source_page_url": source_page_url, "items": []}

    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: (
            "<html>list</html>",
            target_url,
            200,
            "http_cookie",
        ),
    )
    monkeypatch.setattr(live_batch_smoke.time, "sleep", sleep_calls.append)
    monkeypatch.setattr(
        live_batch_smoke,
        "jittered_delay_seconds",
        lambda base, _ratio: base,
    )
    config = live_batch_smoke.LiveSmokeConfig(
        output_dir=Path("."),
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/50025969__2.htm?st_param=2&page=1",
        target_success=1,
        max_attempts=1,
        do_risk=False,
        list_st_params=("2", "1"),
        list_delay_seconds=8.0,
        pacing_jitter_ratio=0.0,
    )

    live_batch_smoke.collect_list_union(FakeProbe, object(), config)

    assert sleep_calls == [8.0]
