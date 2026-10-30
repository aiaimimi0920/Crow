from tools.test.seed_collector_test_context import *  # noqa: F401,F403


def test_parse_seed_sort_specs_accepts_named_final_sort_contract() -> None:
    specs = seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远")

    assert [spec.as_dict() for spec in specs] == [
        {"sort_key": "bid_desc", "st_param": "2", "sort_name": "出价次数由高到低", "sort_order": 0},
        {"sort_key": "end_time_soon", "st_param": "1", "sort_name": "结拍时间由近到远", "sort_order": 1},
    ]

def test_default_seed_sort_specs_start_with_default_then_price_desc() -> None:
    specs = seed_collector.parse_seed_sort_specs(None)

    assert [(spec.sort_key, spec.st_param, spec.sort_name, spec.sort_order) for spec in specs] == [
        ("sort_0", "0", "默认排序", 0),
        ("sort_3", "3", "价格由高到低", 1),
        ("bid_desc", "2", "出价次数由高到低", 2),
        ("end_time_soon", "1", "结拍时间由近到远", 3),
        ("sort_4", "4", "排序4", 4),
        ("sort_5", "5", "排序5", 5),
    ]

def test_parse_seed_job_specs_rejects_non_array_and_missing_location_code() -> None:
    fallback_sort_specs = seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低")

    try:
        seed_collector.parse_seed_job_specs(
            {"location_code": "440115"},
            fallback_sort_specs=fallback_sort_specs,
            fallback_max_page=83,
        )
    except ValueError as exc:
        assert str(exc) == "seed jobs must be a JSON array"
    else:
        raise AssertionError("expected non-array seed jobs to raise ValueError")

    try:
        seed_collector.parse_seed_job_specs(
            [None, {"category": "50025969"}],
            fallback_sort_specs=fallback_sort_specs,
            fallback_max_page=83,
        )
    except ValueError as exc:
        assert str(exc) == "seed job at index 1 requires location_code"
    else:
        raise AssertionError("expected missing location_code to raise ValueError")

def test_should_archive_stale_seed_jobs_rejects_blank_or_duplicate_job_keys() -> None:
    sort_specs = seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低")
    duplicate_job = seed_collector.SeedScanJobSpec(
        job_key="job-1",
        province="广东省",
        city="广州市",
        district="南沙区",
        location_code="440115",
        category="50025969",
        sort_specs=sort_specs,
        max_page=83,
    )
    blank_job = seed_collector.SeedScanJobSpec(
        job_key="",
        province="广东省",
        city="广州市",
        district="南沙区",
        location_code="440115",
        category="50025969",
        sort_specs=sort_specs,
        max_page=83,
    )

    assert (
        seed_collector._should_archive_stale_seed_jobs(
            seed_collector.SeedCollectorConfig(
                job_key="job-1",
                province="广东省",
                city="广州市",
                district="南沙区",
                location_code="440115",
                category="50025969",
                sort_specs=sort_specs,
                max_page=83,
                cdp_endpoint="http://127.0.0.1:9223",
                output_dir=Path("."),
                worker_id="seed-test",
                seed_jobs=(),
            )
        )
        is False
    )
    assert (
        seed_collector._should_archive_stale_seed_jobs(
            seed_collector.SeedCollectorConfig(
                job_key="job-1",
                province="广东省",
                city="广州市",
                district="南沙区",
                location_code="440115",
                category="50025969",
                sort_specs=sort_specs,
                max_page=83,
                cdp_endpoint="http://127.0.0.1:9223",
                output_dir=Path("."),
                worker_id="seed-test",
                seed_jobs=(duplicate_job, duplicate_job),
            )
        )
        is False
    )
    assert (
        seed_collector._should_archive_stale_seed_jobs(
            seed_collector.SeedCollectorConfig(
                job_key="job-1",
                province="广东省",
                city="广州市",
                district="南沙区",
                location_code="440115",
                category="50025969",
                sort_specs=sort_specs,
                max_page=83,
                cdp_endpoint="http://127.0.0.1:9223",
                output_dir=Path("."),
                worker_id="seed-test",
                seed_jobs=(duplicate_job, blank_job),
            )
        )
        is False
    )
    assert (
        seed_collector._should_archive_stale_seed_jobs(
            seed_collector.SeedCollectorConfig(
                job_key="job-1",
                province="广东省",
                city="广州市",
                district="南沙区",
                location_code="440115",
                category="50025969",
                sort_specs=sort_specs,
                max_page=83,
                cdp_endpoint="http://127.0.0.1:9223",
                output_dir=Path("."),
                worker_id="seed-test",
                seed_jobs=(
                    duplicate_job,
                    seed_collector.SeedScanJobSpec(
                        job_key="job-2",
                        province="广东省",
                        city="广州市",
                        district="南沙区",
                        location_code="440115",
                        category="50025969",
                        sort_specs=sort_specs,
                        max_page=83,
                    ),
                ),
            )
        )
        is True
    )

def test_run_seed_collector_once_claims_one_page_and_populates_detail_queue(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(seed_collector, "fetch_json", lambda *a, **kw: {"paused": False})
    repo = _make_repo(tmp_path)
    fetched_urls: list[str] = []
    api_base_urls: list[str | None] = []

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
        api_base_urls.append(api_base_url)
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
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            api_base_url="http://collection-api.test/api",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_page_collected"
    assert summary["task"]["sort_key"] == "bid_desc"
    assert summary["task"]["page"] == 1
    assert summary["upsert"] == {"seen": 2, "new_items": 2, "existing_items": 0, "new_occurrences": 2}
    assert fetched_urls == [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1"
    ]
    assert api_base_urls == ["http://collection-api.test/api"]
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 2

def test_run_seed_collector_once_resumes_after_restart_without_researching_completed_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "seed-resume.sqlite3"
    config = seed_collector.SeedCollectorConfig(
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
    )
    fetched_urls: list[str] = []

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
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)

    first_repo = _make_repo_at(db_path)
    first_summary = seed_collector.run_seed_collector_once(
        config,
        repository=first_repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    restarted_repo = _make_repo_at(db_path)
    second_summary = seed_collector.run_seed_collector_once(
        config,
        repository=restarted_repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert first_summary["task"]["sort_key"] == "bid_desc"
    assert first_summary["task"]["page"] == 1
    assert second_summary["task"]["sort_key"] == "bid_desc"
    assert second_summary["task"]["page"] == 2
    assert fetched_urls == [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=2",
    ]
    assert restarted_repo.seed_queue_counts()["seed_occurrence_total"] == 4

def test_run_seed_collector_once_continues_to_next_page_when_raw_list_has_items_but_filtered_batch_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "seed-failure-only.sqlite3"
    config = seed_collector.SeedCollectorConfig(
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
    )
    fetched_urls: list[str] = []

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
        return "failure-only", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)

    first_repo = _make_repo_at(db_path)
    first_summary = seed_collector.run_seed_collector_once(
        config,
        repository=first_repo,
        http_session=object(),
        browserless_seed_probe=_FailureOnlyProbe,
    )

    restarted_repo = _make_repo_at(db_path)
    second_summary = seed_collector.run_seed_collector_once(
        config,
        repository=restarted_repo,
        http_session=object(),
        browserless_seed_probe=_FailureOnlyProbe,
    )

    assert first_summary["decision"] == "seed_page_collected"
    assert first_summary["item_count"] == 0
    assert first_summary["has_next"] is True
    assert first_summary["task"]["page"] == 1
    assert second_summary["task"]["page"] == 2
    assert fetched_urls == [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=2",
    ]

def test_run_seed_collector_once_marks_scan_page_retryable_on_challenge(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)

    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent, solver_enabled, api_base_url=None: (
            "challenge",
            target_url,
            200,
            "browser_page",
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
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_page_retryable_failure"
    assert summary["reason"] == "list_challenge_page"
    retry = repo.claim_seed_scan_page("seed-retry", lease_seconds=30)
    assert retry is not None
    assert retry["page"] == 1

def test_report_manual_seed_challenge_uses_manual_endpoint_without_sensitive_redirect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reports: list[dict[str, object]] = []

    def _report_captcha_via_api(
        api_base_url: str,
        cdp_endpoint: str,
        target_url: str,
        *,
        manual_only: bool = False,
    ) -> dict[str, object]:
        reports.append(
            {
                "api_base_url": api_base_url,
                "cdp_endpoint": cdp_endpoint,
                "target_url": target_url,
                "manual_only": manual_only,
            }
        )
        return {"status": "manual_required"}

    monkeypatch.setattr(taobao_login_health, "report_captcha_via_api", _report_captcha_via_api)
    config = seed_collector.SeedCollectorConfig(
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
        manual_challenge_reporting=True,
        api_base_url="http://collection-api.test/api",
    )

    result = seed_collector._report_manual_seed_challenge(
        config,
        (
            "https://sf.taobao.com/list/50025969__2.htm?"
            "location_code=440115&page=1&x5secdata=sensitive&redirectURL=https%3A%2F%2Fevil.test"
        ),
    )

    assert result == {"status": "manual_required"}
    assert reports == [
        {
            "api_base_url": "http://collection-api.test/api",
            "cdp_endpoint": "http://127.0.0.1:9223",
            "target_url": (
                "https://sf.taobao.com/list/50025969__2.htm?"
                "location_code=440115&page=1&__captcha_solver_bg=1"
            ),
            "manual_only": True,
        }
    ]
