from tools.test.detail_worker_test_context import *  # noqa: F401,F403


def test_run_detail_worker_once_claims_seed_and_marks_completed(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    processed: list[dict[str, Any]] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed.append(seed)
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        final = {
            "id": seed["id"],
            "title": seed["title"],
            "url": seed["url"],
            "source_url": seed["url"],
            "community_name": "南沙稳定片区",
            "community_stable_key": "collector::广州市::南沙区::南沙稳定片区",
            "city": "广州市",
            "district": "南沙区",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text(json.dumps({"item_id": seed["id"]}, ensure_ascii=False), encoding="utf-8")
        return {"item_id": seed["id"], "final_core": {"source_url": seed["url"], "title": seed["title"]}}

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_completed"
    assert summary["item_id"] == "3001"
    assert [row["id"] for row in processed] == ["3001"]
    assert repo.seed_queue_counts()["seed_item_detail_completed"] == 1
    assert repo.get_flat_item("3001")["community_stable_key"] == "collector::广州市::南沙区::南沙稳定片区"

def test_run_detail_worker_once_raw_only_marks_raw_captured_without_final_json(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    def _process_item(_http, seed, _browser_pages, *, config):
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        (item_dir / "detail.html").write_text("<html>raw</html>", encoding="utf-8")
        (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
        (item_dir / "selected.json").write_text(
            json.dumps({"item_id": seed["id"], "detail_capture_mode": "raw"}, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"item_id": seed["id"], "detail_capture_mode": "raw"}

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            raw_only=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    counts = repo.seed_queue_counts()
    assert summary["decision"] == "detail_item_raw_captured"
    assert summary["item_id"] == "3001"
    assert counts["seed_item_raw_detail_captured"] == 1
    assert counts["seed_item_detail_completed"] == 0
    assert repo.claim_seed_detail_item("detail-test", lease_seconds=30) is None

def test_write_durable_detail_archive_copies_to_dated_partition(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive-root"
    detail_html_path = tmp_path / "detail.html"
    detail_html_path.write_text("<html>raw archive</html>", encoding="utf-8")

    archived_path = detail_worker._write_durable_detail_archive(
        archive_root=archive_root,
        detail_html_path=detail_html_path,
        item_id="3001",
        captured_at=datetime.datetime(2026, 8, 13, 14, 30, 0),
    )

    archived_file = Path(archived_path)
    assert archived_file == archive_root / "html_archive" / "2026" / "2026-08-13" / "item-3001.html"
    assert archived_file.read_text(encoding="utf-8") == "<html>raw archive</html>"

def test_archive_raw_detail_if_configured_swallows_archive_errors(tmp_path: Path, monkeypatch) -> None:
    detail_html_path = tmp_path / "detail.html"
    detail_html_path.write_text("<html>raw archive</html>", encoding="utf-8")

    monkeypatch.setattr(
        detail_worker,
        "_write_durable_detail_archive",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    archived_path = detail_worker._archive_raw_detail_if_configured(
        config=detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            detail_archive_root=tmp_path / "archive-root",
        ),
        detail_html_path=detail_html_path,
        item_id="3001",
    )

    assert archived_path == ""

def test_assert_raw_detail_artifact_is_not_challenge_raises_when_html_is_missing(tmp_path: Path) -> None:
    selected_json_path = tmp_path / "selected.json"
    selected_json_path.write_text("{}", encoding="utf-8")

    try:
        detail_worker._assert_raw_detail_artifact_is_not_challenge(
            detail_html_path=tmp_path / "missing-detail.html",
            selected_json_path=selected_json_path,
        )
    except RuntimeError as exc:
        assert "raw detail artifact missing or unreadable" in str(exc)
    else:
        raise AssertionError("expected missing raw detail artifact to raise RuntimeError")

def test_stage_raw_detail_artifacts_ignores_non_mapping_and_missing_sources(tmp_path: Path) -> None:
    staged = detail_worker._stage_raw_detail_artifacts_for_analysis(
        {
            "id": "3001",
            "_raw_detail_artifacts": {
                "detail_html_path": str(tmp_path / "missing-detail.html"),
                "description_json_path": "",
                "selected_json_path": None,
            },
        },
        output_dir=tmp_path,
        item_id="3001",
    )

    item_dir = tmp_path / "3001"
    assert staged == {}
    assert (item_dir / "seed.json").exists()
    assert not (item_dir / "detail.html").exists()
    assert not (item_dir / "description-data.json").exists()
    assert not (item_dir / "selected.json").exists()

def test_archive_raw_detail_if_configured_returns_empty_when_disabled_or_source_missing(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    detail_html_path = tmp_path / "missing-detail.html"

    monkeypatch.setattr(
        detail_worker,
        "_write_durable_detail_archive",
        lambda **kwargs: calls.append(kwargs) or "should-not-be-used",
    )

    disabled_archive_path = detail_worker._archive_raw_detail_if_configured(
        config=detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            detail_archive_root=None,
        ),
        detail_html_path=detail_html_path,
        item_id="3001",
    )
    missing_source_archive_path = detail_worker._archive_raw_detail_if_configured(
        config=detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            detail_archive_root=tmp_path / "archive-root",
        ),
        detail_html_path=detail_html_path,
        item_id="3001",
    )

    assert disabled_archive_path == ""
    assert missing_source_archive_path == ""
    assert calls == []

def test_seed_collector_metadata_reaches_detail_worker_and_live_target_uses_detail_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    collected_urls: list[str] = []
    captured: list[dict[str, object]] = []

    class _SingleItemProbe:
        DEFAULT_USER_AGENT = "fake-agent"

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, Any]:
            return {
                "item_count": 1,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
                "body_snippet": final_url,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, Any] | None:
            return {"data": [{"id": "4001"}]}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, Any]:
            return {
                "source_page_url": source_page_url,
                "items": [
                    {
                        "id": "4001",
                        "title": "跨模块详情元数据测试",
                        "url": "https://sf-item.taobao.com/sf_item/4001.htm",
                    }
                ],
            }

    def _fetch_list_page(
        _http,
        *,
        cdp_endpoint: str,
        target_url: str,
        user_agent: str,
        solver_enabled: bool,
        api_base_url: str | None = None,
    ):
        collected_urls.append(target_url)
        return "ok", "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&page=1&from=browser", 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)
    monkeypatch.setattr(seed_collector, "resolve_runtime_user_agent", lambda _endpoint: "collector-ua")

    seed_summary = seed_collector.run_seed_collector_once(
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
        browserless_seed_probe=_SingleItemProbe,
    )

    def _process_item(_http, seed, _browser_pages, *, config):
        captured.append(
            {
                "seed": dict(seed),
                "target_url": config.target_url,
            }
        )
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        final = {
            "id": seed["id"],
            "title": seed["title"],
            "url": seed["url"],
            "source_url": seed["url"],
            "community_name": "跨模块小区",
            "community_stable_key": "collector::广州市::南沙区::跨模块小区",
            "city": "广州市",
            "district": "南沙区",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text(
            json.dumps({"item_id": seed["id"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"item_id": seed["id"], "final_core": {"source_url": seed["url"], "title": seed["title"]}}

    detail_summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert seed_summary["decision"] == "seed_page_collected"
    assert collected_urls == [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1"
    ]
    assert detail_summary["decision"] == "detail_item_completed"
    assert len(captured) == 1
    seed_payload = captured[0]["seed"]
    assert seed_payload["source_page_url"] == (
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&page=1&from=browser"
    )
    assert seed_payload["list_page"] == 1
    assert seed_payload["list_sort_key"] == "bid_desc"
    assert seed_payload["list_st_param"] == "2"
    assert captured[0]["target_url"] == "https://sf-item.taobao.com/sf_item/4001.htm"

def test_run_detail_worker_once_raw_only_rejects_challenge_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(detail_worker, "fetch_json", lambda *a, **kw: {"paused": False})
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    solver_reports: list[tuple[str, str, str]] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        (item_dir / "detail.html").write_text(
            "<html><title>安全验证</title><body>验证码 x5secdata</body></html>",
            encoding="utf-8",
        )
        (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
        (item_dir / "selected.json").write_text(
            json.dumps(
                {
                    "item_id": seed["id"],
                    "detail_capture_mode": "raw",
                    "fetch": {
                        "detail_final_url": "https://sf-item.taobao.com/sf_item/3001.htm/_____tmd_____/punish?x5secdata=abc",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"item_id": seed["id"], "detail_capture_mode": "raw"}

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda api_base_url, cdp_endpoint, target_url: solver_reports.append(
            (api_base_url, cdp_endpoint, target_url)
        )
        or {"status": "queued"},
    )

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            raw_only=True,
            solver_enabled=True,
            api_base_url="http://collector.local/api",
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    counts = repo.seed_queue_counts()
    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["reason"] == "detail_challenge_page"
    assert summary["retry_budget_preserved"] is True
    assert summary["captcha_solver_report"] == {"status": "queued"}
    assert solver_reports == [
        ("http://collector.local/api", "http://127.0.0.1:9223", "https://sf-item.taobao.com/sf_item/3001.htm")
    ]
    assert counts["seed_item_raw_detail_captured"] == 0
    assert counts["seed_item_pending_detail"] == 1
