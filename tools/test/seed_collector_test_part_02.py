from tools.test.seed_collector_test_context import *  # noqa: F401,F403


def test_run_seed_collector_once_reports_challenge_and_observes_manual_pause(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    reported_targets: list[str] = []
    solver_flags: list[bool] = []
    pause_states = iter(
        [
            {"paused": False, "captcha_solver": {}},
            {
                "paused": True,
                "reason": "captcha_solver_manual_required",
                "captcha_solver": {"manual_required": True},
            },
        ]
    )
    monkeypatch.setattr(seed_collector, "_collection_pause_state_with_retry", lambda _api: next(pause_states))
    monkeypatch.setattr(
        seed_collector,
        "_report_manual_seed_challenge",
        lambda _config, target_url: reported_targets.append(target_url) or {"status": "manual_required"},
    )

    def _fetch_list_page(
        _http,
        *,
        cdp_endpoint: str,
        target_url: str,
        user_agent: str,
        solver_enabled: bool,
        api_base_url: str | None = None,
    ) -> tuple[str, str, int, str]:
        solver_flags.append(solver_enabled)
        return (
            "challenge",
            target_url + "/_____tmd_____/punish?x5secdata=secret",
            200,
            "http_cookie_challenge",
        )

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)

    summary = seed_collector.run_seed_collector_once(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            solver_enabled=True,
            manual_challenge_reporting=True,
            api_base_url="http://collection-api.test/api",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_collection_paused"
    assert summary["reason"] == "captcha_solver_manual_required"
    assert "captcha_solver_report" not in summary
    assert reported_targets == []
    assert solver_flags == [True]

def test_run_seed_collector_once_marks_browser_payload_missing_page_retryable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(seed_collector, "fetch_json", lambda *a, **kw: {"paused": False})
    repo = _make_repo(tmp_path)

    class _BrowserShellProbe:
        DEFAULT_USER_AGENT = "fake-agent"

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, Any]:
            return {
                "has_script": False,
                "item_count": None,
                "first_ids": [],
                "first_urls": [],
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
                "body_snippet": final_url,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, Any] | None:
            return None

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, Any]:
            return {"source_page_url": source_page_url, "items": []}

    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent, solver_enabled, api_base_url=None: (
            "<!doctype html><html><body>browser shell</body></html>",
            target_url,
            None,
            "browser_page_after_http_challenge",
        ),
    )

    summary = seed_collector.run_seed_collector_once(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            solver_enabled=True,
            api_base_url="http://collection-api.test/api",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_BrowserShellProbe,
    )

    assert summary["decision"] == "seed_page_retryable_failure"
    assert summary["reason"] == "browser_list_payload_missing"
    assert summary["fetch"]["method"] == "browser_page_after_http_challenge"
    retry = repo.claim_seed_scan_page("seed-retry", lease_seconds=30)
    assert retry is not None
    assert retry["page"] == 1

def test_run_seed_collector_once_treats_punish_final_url_shell_as_challenge(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(seed_collector, "fetch_json", lambda *a, **kw: {"paused": False})
    repo = _make_repo(tmp_path)

    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent, solver_enabled, api_base_url=None: (
            "<!doctype html><html><body>browser shell</body></html>",
            target_url + "/_____tmd_____/punish?x5secdata=abc",
            None,
            "browser_page_after_http_challenge",
        ),
    )

    summary = seed_collector.run_seed_collector_once(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            solver_enabled=True,
            api_base_url="http://collection-api.test/api",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=browserless_seed_probe,
    )

    assert summary["decision"] == "seed_page_retryable_failure"
    assert summary["reason"] == "list_challenge_page"

def test_run_seed_collector_once_pauses_and_requeues_when_cdp_endpoint_is_unreachable(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)

    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            live_batch_smoke.CdpEndpointUnavailableError(
                "http://127.0.0.1:9223",
                "open_list_page_target",
                TimeoutError("timed out"),
            )
        ),
    )

    summary = seed_collector.run_seed_collector_once(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            auth_probe_interval_seconds=10,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_collection_paused"
    assert summary["reason"] == "cdp_unreachable"
    assert summary["auth_probe"]["attempted"] is True
    assert summary["auth_probe"]["authenticated"] is False
    assert summary["auth_probe"]["status"] == "cdp_unreachable"
    retry = repo.claim_seed_scan_page("seed-retry", lease_seconds=30)
    assert retry is not None
    assert retry["page"] == 1

def test_run_seed_collector_once_passes_solver_enabled_to_fetch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(seed_collector, "fetch_json", lambda *a, **kw: {"paused": False})
    repo = _make_repo(tmp_path)
    solver_flags: list[bool] = []

    def _fetch_list_page(
        _http,
        *,
        cdp_endpoint: str,
        target_url: str,
        user_agent: str,
        solver_enabled: bool,
        api_base_url: str | None = None,
    ):
        solver_flags.append(solver_enabled)
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)

    summary = seed_collector.run_seed_collector_once(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            solver_enabled=True,
            api_base_url="http://collection-api.test/api",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_page_collected"
    assert solver_flags == [True]

def test_run_seed_collector_once_skips_page_fetch_when_collection_api_reports_manual_required(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(
        seed_collector,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {"manual_required": True},
        },
    )
    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("manual-required workers must not fetch pages")),
    )

    summary = seed_collector.run_seed_collector_once(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_collection_paused"
    assert summary["reason"] == "captcha_solver_manual_required"
    assert summary["captcha_solver"]["manual_required"] is True

def test_run_seed_collector_once_probes_default_list_when_manual_required_lacks_last_request(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    fetched_urls: list[str] = []
    solver_flags: list[bool] = []
    resumed: list[dict[str, Any]] = []
    monkeypatch.setattr(
        seed_collector,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {"manual_required": True},
        },
    )

    def _fetch_list_page(
        _http,
        *,
        cdp_endpoint: str,
        target_url: str,
        user_agent: str,
        solver_enabled: bool,
        api_base_url: str | None = None,
    ):
        fetched_urls.append(target_url)
        solver_flags.append(solver_enabled)
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)
    monkeypatch.setattr(
        seed_collector,
        "_notify_auth_probe_passed",
        lambda api_base_url, target_url: resumed.append({"api_base_url": api_base_url, "target_url": target_url})
        or {"ok": True, "auth_state_confirmed": True, "scope": "seed"},
    )

    summary = seed_collector.run_seed_collector_once(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            solver_enabled=True,
            api_base_url="http://collection-api.test/api",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_page_collected"
    assert summary["auth_probe"]["authenticated"] is True
    assert fetched_urls == [
        "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1",
    ]
    assert solver_flags == [False, True]
    assert resumed == [
        {
            "api_base_url": "http://collection-api.test/api",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
        }
    ]
