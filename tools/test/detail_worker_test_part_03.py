from tools.test.detail_worker_test_context import *  # noqa: F401,F403


def test_run_detail_analysis_once_persists_latest_module_b_receipt_on_failure(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    claimed = repo.claim_seed_detail_item("raw-worker", lease_seconds=30)
    assert claimed is not None
    item_dir = tmp_path / "3001"
    item_dir.mkdir()
    (item_dir / "detail.html").write_text("<html>raw</html>", encoding="utf-8")
    (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
    (item_dir / "selected.json").write_text("{}", encoding="utf-8")
    repo.mark_seed_raw_detail_captured(
        "3001",
        detail_html_path=str(item_dir / "detail.html"),
        description_json_path=str(item_dir / "description-data.json"),
        selected_json_path=str(item_dir / "selected.json"),
    )
    receipt = {
        "schema_version": "analysis_module_b_v1",
        "run_id": "5" * 64,
        "item_id": "3001",
        "input_sha256": "6" * 64,
        "mode": "primary",
        "status": "candidate_partial",
        "candidate_models": ["flash", "pro", "grok"],
        "arbiter_model": "arbiter",
        "arbiter_independent_model": True,
        "artifacts": {},
    }

    def _analyze_raw_item(_item_id: str, *, output_dir: Path, do_risk: bool):
        assert output_dir == tmp_path
        assert do_risk is False
        analysis_dir = item_dir / "analysis-b"
        analysis_dir.mkdir()
        (analysis_dir / "latest.json").write_text(json.dumps(receipt), encoding="utf-8")
        raise live_batch_smoke.AnalysisModuleBIncompleteError("candidate_partial")

    summary = detail_worker.run_detail_analysis_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="analysis-test",
            do_risk=False,
            analysis_only=True,
        ),
        repository=repo,
        analyze_item_func=_analyze_raw_item,
    )

    stored = repo.get_analysis_ensemble_run("5" * 64)
    assert summary["decision"] == "detail_analysis_retryable_failure"
    assert stored is not None
    assert stored["status"] == "candidate_partial"

def test_run_detail_analysis_once_releases_claim_without_consuming_retry_budget_when_llm_backend_unavailable(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    claimed = repo.claim_seed_detail_item("raw-worker", lease_seconds=30)
    assert claimed is not None
    item_dir = tmp_path / "3001"
    item_dir.mkdir()
    (item_dir / "detail.html").write_text("<html>raw</html>", encoding="utf-8")
    (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
    (item_dir / "selected.json").write_text(
        json.dumps({"item_id": "3001", "detail_capture_mode": "raw"}, ensure_ascii=False),
        encoding="utf-8",
    )
    repo.mark_seed_raw_detail_captured(
        "3001",
        detail_html_path=str(item_dir / "detail.html"),
        description_json_path=str(item_dir / "description-data.json"),
        selected_json_path=str(item_dir / "selected.json"),
    )

    def _analyze_raw_item(_item_id: str, *, output_dir: Path, do_risk: bool):
        assert output_dir == tmp_path
        assert do_risk is False
        raise RuntimeError("LLM backend unavailable: AppIdNoAuthError")

    summary = detail_worker.run_detail_analysis_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="analysis-test",
            do_risk=False,
            analysis_only=True,
        ),
        repository=repo,
        analyze_item_func=_analyze_raw_item,
    )

    counts = repo.seed_queue_counts()
    assert summary["decision"] == "detail_analysis_backend_unavailable"
    assert summary["item_id"] == "3001"
    assert counts["seed_item_raw_detail_captured"] == 1
    assert counts["seed_item_analysis_in_progress"] == 0
    assert counts["seed_item_analysis_failed"] == 0
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert row is not None
        assert row.status == "raw_detail_captured"
        assert row.detail_leased_by is None
        payload = dict(row.source_payload or {})
        assert payload.get("_analysis_attempt_count") in (0, None)
        assert "LLM backend unavailable" in str(row.detail_last_error or "")

def test_build_runtime_context_tolerates_open_browser_page_cache_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(detail_worker, "export_cookies", lambda _endpoint: [{"name": "cookie2", "value": "abc"}])
    monkeypatch.setattr(detail_worker, "build_http", lambda _cookies: "http-session")
    monkeypatch.setattr(detail_worker, "load_open_browser_pages", lambda _endpoint: {})

    http_session, browser_pages = detail_worker._build_runtime_context(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        )
    )

    assert http_session == "http-session"
    assert browser_pages == {}

def test_build_runtime_context_skips_open_browser_page_cache_when_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES", "0")
    monkeypatch.setattr(detail_worker, "export_cookies", lambda _endpoint: [{"name": "cookie2", "value": "abc"}])
    monkeypatch.setattr(detail_worker, "build_http", lambda _cookies: "http-session")

    def _fail_load_open_browser_pages(_endpoint):
        raise AssertionError("open browser page cache should not be loaded")

    monkeypatch.setattr(detail_worker, "load_open_browser_pages", _fail_load_open_browser_pages)

    http_session, browser_pages = detail_worker._build_runtime_context(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:1",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        )
    )

    assert http_session == "http-session"
    assert browser_pages == {}

def test_run_detail_worker_once_marks_retryable_failure(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    def _process_item(_http, seed, _browser_pages, *, config):
        raise RuntimeError("detail timeout")

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

    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["item_id"] == "3001"
    assert summary["error"] == "RuntimeError: runtime_error"
    retry = repo.claim_seed_detail_item("detail-retry", lease_seconds=30)
    assert retry is not None
    assert retry["id"] == "3001"

def test_run_detail_worker_once_does_not_consume_retry_budget_for_transient_dns_failure(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise RuntimeError(
            "ConnectionError(MaxRetryError('HTTPSConnectionPool(host=\\'sf-item.taobao.com\\', port=443): "
            "Max retries exceeded (Caused by NameResolutionError(\"Failed to resolve "
            "\\'sf-item.taobao.com\\' ([Errno -3] Temporary failure in name resolution)\"))'))"
        )

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

    assert summary["decision"] == "detail_item_retryable_failure"
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert row is not None
        assert row.status == "pending_detail"
        assert row.detail_attempt_count == 0

def test_collection_pause_state_reads_status_via_direct_internal_api(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_fetch_json(url: str, *, timeout: float):
        captured["url"] = url
        captured["timeout"] = timeout
        return {"paused": True, "captcha_solver": {"manual_required": True}}

    monkeypatch.setattr(detail_worker, "fetch_json", _fake_fetch_json)

    pause_state = detail_worker._collection_pause_state("http://192.168.15.200:8001/api")

    assert pause_state == {
        "paused": True,
        "reason": "captcha_solver_manual_required",
        "captcha_solver": {"manual_required": True},
    }
    assert captured == {
        "url": "http://192.168.15.200:8001/api/status",
        "timeout": 5,
    }

def test_collection_pause_state_returns_status_unavailable_for_non_object_payload(monkeypatch) -> None:
    monkeypatch.setattr(detail_worker, "fetch_json", lambda _url, *, timeout: ["paused"])

    pause_state = detail_worker._collection_pause_state("http://192.168.15.200:8001/api")

    assert pause_state == {
        "paused": False,
        "reason": "status_unavailable",
        "error": "non_object_status",
    }

def test_detail_pause_state_pauses_during_same_node_solver(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_NODE_ID", "pc2")
    monkeypatch.setattr(
        detail_worker,
        "fetch_json",
        lambda _url, *, timeout: {
            "paused": False,
            "captcha_solver": {
                "running": True,
                "paused": True,
                "manual_required": False,
                "last_request": {"node_id": "pc2"},
            },
        },
    )

    pause_state = detail_worker._collection_pause_state("http://192.168.15.200:8001/api")

    assert pause_state["paused"] is True
    assert pause_state["reason"] == "captcha_solver_running"

def test_detail_pause_state_ignores_solver_running_for_other_node(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_NODE_ID", "pc3")
    monkeypatch.setattr(
        detail_worker,
        "fetch_json",
        lambda _url, *, timeout: {
            "paused": True,
            "captcha_solver": {
                "running": True,
                "paused": True,
                "manual_required": False,
                "last_request": {"node_id": "pc2"},
            },
        },
    )

    pause_state = detail_worker._collection_pause_state("http://192.168.15.200:8001/api")

    assert pause_state["paused"] is False
    assert pause_state["reason"] == "captcha_solver_running_other_node"

def test_run_detail_worker_once_skips_claiming_items_when_collection_api_reports_manual_required(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    processed: list[str] = []

    monkeypatch.setattr(
        detail_worker,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {"manual_required": True},
        },
    )

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=lambda *_args, **_kwargs: processed.append("called") or {},
    )

    assert summary["decision"] == "detail_collection_paused"
    assert summary["reason"] == "captcha_solver_manual_required"
    assert summary["captcha_solver"]["manual_required"] is True
    assert processed == []
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 1

def test_run_detail_worker_once_ignores_manual_required_when_target_detail_page_is_already_open(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    processed: list[str] = []

    monkeypatch.setattr(
        detail_worker,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {
                "manual_required": True,
                "last_request": {
                    "target_url": "https://sf-item.taobao.com/sf_item/3001.htm?track_id=test&__captcha_solver_bg=1",
                },
            },
        },
    )

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={
            "3001": (
                "<html><body><h1>竞买公告</h1><div>标的物介绍</div></body></html>",
                "https://sf-item.taobao.com/sf_item/3001.htm?track_id=test",
            )
        },
        process_item_func=lambda *_args, **_kwargs: processed.append("called") or {"item_id": "3001", "final_core": {}},
    )

    assert summary["decision"] == "detail_item_completed"
    assert summary["item_id"] == "3001"
    assert processed == ["called"]

def test_run_detail_worker_once_keeps_manual_required_when_open_detail_page_is_still_challenge(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    processed: list[str] = []

    monkeypatch.setattr(
        detail_worker,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {
                "manual_required": True,
                "last_request": {
                    "target_url": "https://sf-item.taobao.com/sf_item/3001.htm?track_id=test&__captcha_solver_bg=1",
                },
            },
        },
    )

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={
            "3001": (
                "<script>var url='https://sf-item.taobao.com//sf_item/3001.htm/_____tmd_____/punish?x5secdata=abc';</script>",
                "https://sf-item.taobao.com/sf_item/3001.htm?track_id=test",
            )
        },
        process_item_func=lambda *_args, **_kwargs: processed.append("called") or {"item_id": "3001", "final_core": {}},
    )

    assert summary["decision"] == "detail_collection_paused"
    assert summary["reason"] == "captcha_solver_manual_required"
    assert processed == []
