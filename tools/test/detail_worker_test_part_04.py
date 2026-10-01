from tools.test.detail_worker_test_context import *  # noqa: F401,F403


def test_run_detail_worker_once_retries_initial_status_unavailable_before_claiming_item(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    pause_states = [
        {"paused": False, "reason": "status_unavailable", "error": "api starting"},
        {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {"manual_required": True},
        },
    ]
    sleep_calls: list[float] = []
    processed: list[str] = []

    monkeypatch.setattr(detail_worker, "_collection_pause_state", lambda _api_base_url: pause_states.pop(0))
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

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
    assert sleep_calls == [1.0]
    assert processed == []
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 1

def test_run_detail_worker_once_reports_solver_when_detail_challenge_appears(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    reports: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda api_base_url, cdp_endpoint, target_url: (
            reports.append((api_base_url, cdp_endpoint, target_url)) or {"status": "solving"}
        ),
    )

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise RuntimeError("browser detail request returned anti-bot challenge")

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
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["reason"] == "detail_challenge_page"
    assert summary["captcha_solver_report"] == {"status": "solving"}
    assert reports == [
        (
            "http://collection-api.test/api",
            "http://127.0.0.1:9223",
            "https://sf-item.taobao.com/sf_item/3001.htm",
        )
    ]

def test_run_detail_worker_once_prefers_enabled_solver_over_manual_reporting(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    reports: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda *args, **kwargs: reports.append((args, kwargs)) or {"status": "manual_required"},
    )

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise RuntimeError("browser detail request returned anti-bot challenge")

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9225",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=True,
            manual_challenge_reporting=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["reason"] == "detail_challenge_page"
    assert summary["captcha_solver_report"] == {"status": "manual_required"}
    assert reports == [
        (
            (
                "http://collection-api.test/api",
                "http://127.0.0.1:9225",
                "https://sf-item.taobao.com/sf_item/3001.htm",
            ),
            {},
        )
    ]

def test_run_detail_worker_once_records_report_failure_when_captcha_report_raises(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("captcha report offline")),
    )

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise RuntimeError("browser detail request returned anti-bot challenge")

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
        process_item_func=_process_item,
    )

    assert summary["reason"] == "detail_challenge_page"
    assert summary["captcha_solver_report"]["status"] == "report_failed"
    assert summary["captcha_solver_report"]["error"] == "RuntimeError: runtime_error"

def test_run_detail_worker_once_does_not_report_when_solver_and_manual_reporting_are_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("solver reporting should be disabled")),
    )

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise RuntimeError("browser detail request returned anti-bot challenge")

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=False,
            manual_challenge_reporting=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["reason"] == "detail_challenge_page"
    assert "captcha_solver_report" not in summary

def test_llm_preflight_network_unavailable_is_treated_as_unavailable() -> None:
    assert detail_worker._llm_preflight_is_unavailable(
        {"enabled": True, "status_code": 0, "error_type": "ConnectTimeout"}
    ) is True

def test_llm_preflight_retries_transient_chat_failure_and_recovers(tmp_path: Path, monkeypatch) -> None:
    responses = [
        {"enabled": True, "status_code": 200, "chat_status_code": 503},
        {"enabled": True, "status_code": 200, "chat_status_code": 200},
    ]
    calls: list[dict[str, object]] = []
    sleep_calls: list[float] = []

    def _preflight_llm_backend(*, timeout: float, check_chat: bool = False) -> dict[str, object]:
        calls.append({"timeout": timeout, "check_chat": check_chat})
        return responses.pop(0)

    monkeypatch.setattr(detail_worker, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setattr(detail_worker.time, "sleep", sleep_calls.append)

    result = detail_worker._run_llm_preflight(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="analysis-test",
            do_risk=False,
            llm_preflight_enabled=True,
            llm_preflight_timeout_seconds=2.5,
            llm_preflight_attempts=3,
            llm_preflight_retry_delay_seconds=1.5,
            analysis_only=True,
        )
    )

    assert result is not None
    assert result["chat_status_code"] == 200
    assert result["attempt"] == 2
    assert result["max_attempts"] == 3
    assert calls == [
        {"timeout": 2.5, "check_chat": True},
        {"timeout": 2.5, "check_chat": True},
    ]
    assert sleep_calls == [1.5]

def test_run_detail_worker_once_preserves_retry_budget_when_detail_challenge_appears(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda *_args, **_kwargs: {"status": "already_running"},
    )

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise RuntimeError("browser detail request returned anti-bot challenge")

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
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["reason"] == "detail_challenge_page"
    assert summary["retry_budget_preserved"] is True
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert row is not None
        assert row.status == "pending_detail"
        assert row.detail_attempt_count == 0

def test_run_detail_worker_once_preserves_retry_budget_when_detail_cdp_endpoint_is_unreachable(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise live_batch_smoke.CdpEndpointUnavailableError(
            "http://127.0.0.1:9223",
            "connect_over_cdp",
            TimeoutError("timed out"),
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
    assert summary["reason"] == "detail_cdp_unreachable"
    assert summary["retry_budget_preserved"] is True
    assert summary["cdp_health"]["status"] == "cdp_unreachable"
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert row is not None
        assert row.status == "pending_detail"
        assert row.detail_attempt_count == 0

def test_run_detail_worker_batch_does_not_retry_same_failed_item_in_same_batch(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001", "3002"])
    processed: list[str] = []
    sleep_calls: list[float] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed.append(str(seed["id"]))
        if seed["id"] == "3001":
            raise RuntimeError("llm backend 503")
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        final = {
            "id": seed["id"],
            "title": seed["title"],
            "url": seed["url"],
            "source_url": seed["url"],
            "community_name": "南沙稳定片区",
            "community_stable_key": f"collector::广州市::南沙区::{seed['id']}",
            "city": "广州市",
            "district": "南沙区",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text(json.dumps({"item_id": seed["id"]}, ensure_ascii=False), encoding="utf-8")
        return {"item_id": seed["id"], "final_core": {"source_url": seed["url"], "title": seed["title"]}}

    monkeypatch.setattr(detail_worker.time, "sleep", sleep_calls.append)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=2,
            worker_id="detail-test",
            do_risk=False,
            success_delay_seconds=9.0,
            failure_delay_seconds=1.25,
            pacing_jitter_ratio=0.0,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert processed == ["3001", "3002"]
    assert summary["attempts"] == 2
    assert summary["completed"] == 1
    assert [result["item_id"] for result in summary["results"]] == ["3001", "3002"]
    assert sleep_calls == [1.25]

def test_run_detail_worker_batch_applies_default_jittered_delay_between_successful_items(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    sleep_calls: list[float] = []
    results = iter(
        [
            {"decision": "detail_item_raw_captured", "item_id": "3001"},
            {"decision": "detail_item_raw_captured", "item_id": "3002"},
        ]
    )

    monkeypatch.setattr(detail_worker, "run_detail_worker_once", lambda *_args, **_kwargs: next(results))
    monkeypatch.setattr(detail_worker.time, "sleep", sleep_calls.append)
    monkeypatch.setattr(
        detail_worker,
        "jittered_delay_seconds",
        lambda base, ratio: base + ratio,
    )

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=2,
            max_attempts=2,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
    )

    assert summary["completed"] == 2
    assert sleep_calls == [6.35]
