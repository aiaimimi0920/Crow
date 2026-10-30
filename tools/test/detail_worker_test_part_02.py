from tools.test.detail_worker_test_context import *  # noqa: F401,F403


def test_run_detail_worker_once_ignores_challenge_suppressed_after_recent_detail_progress(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(detail_worker, "fetch_json", lambda *a, **kw: {"paused": False})
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

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
                    "fetch": {
                        "detail_final_url": (
                            "https://sf-item.taobao.com/sf_item/3001.htm/"
                            "_____tmd_____/punish?x5secdata=stale"
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )
        return {"item_id": seed["id"], "detail_capture_mode": "raw"}

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda *_args, **_kwargs: {
            "status": "recent_auth_complete",
            "reason": "recent_detail_progress",
            "captured_since_auth": 2,
            "retry_after_seconds": 42,
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
            raw_only=True,
            solver_enabled=True,
            api_base_url="http://collector.local/api",
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["reason"] == "detail_stale_challenge_ignored"
    assert summary["challenge_suppressed"] is True
    assert summary["retry_budget_preserved"] is True
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 1

def test_recent_force_reset_response_suppresses_detail_challenge() -> None:
    assert detail_worker._captcha_report_suppresses_challenge(
        {"status": "recent_force_reset", "scope": "detail"}
    ) is True

def test_recent_force_reset_stops_detail_batch_and_honors_retry_after(tmp_path: Path) -> None:
    config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://127.0.0.1:9223",
        target_success=10,
        max_attempts=30,
        worker_id="detail-test",
        do_risk=False,
        solver_enabled=True,
        loop_interval_seconds=30,
        challenge_cooldown_seconds=60,
    )
    item_result = {
        "decision": "detail_item_retryable_failure",
        "reason": "detail_stale_challenge_ignored",
        "captcha_solver_report": {
            "status": "recent_force_reset",
            "scope": "detail",
            "retry_after_seconds": 142,
        },
    }

    assert detail_worker._detail_challenge_should_break_batch(config, item_result) is True
    assert detail_worker._detail_batch_sleep_seconds(
        config,
        {"completed": 0, "results": [item_result]},
    ) == 142

def test_run_detail_worker_once_raw_only_rejects_login_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(detail_worker, "fetch_json", lambda *a, **kw: {"paused": False})
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    solver_reports: list[tuple[str, str, str]] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        (item_dir / "detail.html").write_text(
            "<html><title>登录</title><body>扫码登录 login.taobao.com</body></html>",
            encoding="utf-8",
        )
        (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
        (item_dir / "selected.json").write_text(
            json.dumps(
                {
                    "item_id": seed["id"],
                    "detail_capture_mode": "raw",
                    "fetch": {
                        "detail_final_url": "https://login.taobao.com/havanaone/login/login.htm?redirectURL=https%3A%2F%2Fsf-item.taobao.com%2Fsf_item%2F3001.htm",
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

def test_run_detail_worker_once_passes_failure_cooldown_to_repository(tmp_path: Path) -> None:
    class SpyRepository:
        def __init__(self) -> None:
            self.claim_kwargs: dict[str, Any] | None = None

        def claim_seed_detail_item(self, _worker_id: str, **kwargs: Any):
            self.claim_kwargs = dict(kwargs)
            return None

        def seed_queue_counts(self) -> dict[str, int]:
            return {}

    repository = SpyRepository()

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            failure_cooldown_seconds=1800,
        ),
        repository=repository,  # type: ignore[arg-type]
        http_session=object(),
        browser_pages={},
        process_item_func=lambda *_args, **_kwargs: {},
    )

    assert summary == {
        "decision": "detail_queue_empty",
        "claimed_items": 0,
        "process_item_calls": 0,
        "analysis_item_calls": 0,
        "paused_results": 0,
    }
    assert repository.claim_kwargs is not None
    assert repository.claim_kwargs["failure_cooldown_seconds"] == 1800

def test_detail_worker_config_reads_failure_cooldown_env(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_DETAIL_FAILURE_COOLDOWN_SECONDS", "1800")

    config, _loop = detail_worker.config_from_env_and_args([])

    assert config.failure_cooldown_seconds == 1800

def test_detail_worker_config_reads_per_attempt_delay_env(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_DETAIL_SUCCESS_DELAY_SECONDS", "0.25")
    monkeypatch.setenv("FAPAI_DETAIL_FAILURE_DELAY_SECONDS", "1.75")
    monkeypatch.setenv("FAPAI_DETAIL_PACING_JITTER_RATIO", "0.2")
    monkeypatch.setenv("FAPAI_DETAIL_CHALLENGE_COOLDOWN_SECONDS", "480")

    config, _loop = detail_worker.config_from_env_and_args([])

    assert config.success_delay_seconds == 0.25
    assert config.failure_delay_seconds == 1.75
    assert config.pacing_jitter_ratio == 0.2
    assert config.challenge_cooldown_seconds == 480

def test_detail_worker_report_keeps_real_taobao_on_automatic_solver_path(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        taobao_login_health,
        "report_captcha_via_api",
        lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs) or {"status": "manual_required"},
    )

    result = detail_worker._report_captcha_solver(
        "http://collection-api.test/api",
        "http://127.0.0.1:9225",
        "https://sf-item.taobao.com/sf_item/3001.htm",
    )

    assert result == {"status": "manual_required"}
    assert captured["kwargs"] == {"scope": "detail"}

def test_detail_worker_config_reads_llm_preflight_retry_env(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_LLM_PREFLIGHT_ATTEMPTS", "4")
    monkeypatch.setenv("FAPAI_LLM_PREFLIGHT_RETRY_DELAY_SECONDS", "1.5")

    config, _loop = detail_worker.config_from_env_and_args([])

    assert config.llm_preflight_attempts == 4
    assert config.llm_preflight_retry_delay_seconds == 1.5

def test_run_detail_analysis_once_claims_raw_item_while_collection_is_paused(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Analysis consumes raw artifacts independently; a collection pause must not
    # call or gate the analysis worker's queue claim.
    monkeypatch.setattr(
        detail_worker,
        "_collection_pause_state",
        lambda _api_base_url: (_ for _ in ()).throw(
            AssertionError("analysis-only must not read collection pause state")
        ),
    )
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

    def _analyze_raw_item(item_id: str, *, output_dir: Path, do_risk: bool):
        assert item_id == "3001"
        assert output_dir == tmp_path
        assert do_risk is False
        final = {
            "id": item_id,
            "title": "南沙详情 A",
            "source_url": "https://sf-item.taobao.com/sf_item/3001.htm",
            "community_name": "南沙分析小区",
            "community_stable_key": "collector::广州市::南沙区::南沙分析小区",
            "city": "广州市",
            "district": "南沙区",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text(json.dumps({"item_id": item_id}, ensure_ascii=False), encoding="utf-8")
        return {"item_id": item_id, "final_core": {"title": "南沙详情 A"}}

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
    assert summary["decision"] == "detail_analysis_completed"
    assert summary["item_id"] == "3001"
    assert counts["seed_item_detail_completed"] == 1
    assert counts["seed_item_raw_detail_captured"] == 0
    assert counts["seed_item_analysis_in_progress"] == 0
    assert repo.get_flat_item("3001")["community_stable_key"] == "collector::广州市::南沙区::南沙分析小区"

def test_run_detail_analysis_once_persists_module_b_receipt_on_success(tmp_path: Path) -> None:
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
        "run_id": "3" * 64,
        "item_id": "3001",
        "input_sha256": "4" * 64,
        "mode": "shadow",
        "status": "finalized",
        "candidate_models": ["flash", "pro", "grok"],
        "arbiter_model": "arbiter",
        "arbiter_independent_model": True,
        "analysis_provenance": {
            "module": "B",
            "pipeline_version": "analysis_module_b_v1",
            "run_id": "3" * 64,
            "input_sha256": "4" * 64,
            "model_routing_sha256": "7" * 64,
        },
        "artifacts": {"receipt_path": str(item_dir / "analysis-b" / "receipt.json")},
    }

    def _analyze_raw_item(item_id: str, *, output_dir: Path, do_risk: bool):
        assert item_id == "3001"
        assert output_dir == tmp_path
        assert do_risk is False
        final = {
            "id": item_id,
            "title": "南沙详情 A",
            "source_url": "https://sf-item.taobao.com/sf_item/3001.htm",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text("{}", encoding="utf-8")
        return {"item_id": item_id, "analysis_module_b": receipt}

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

    stored = repo.get_analysis_ensemble_run("3" * 64)
    assert summary["decision"] == "detail_analysis_completed"
    assert stored is not None
    assert stored["status"] == "finalized"
    assert stored["receipt"]["analysis_provenance"]["module"] == "B"
