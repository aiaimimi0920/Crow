from tools.test.detail_worker_test_context import *  # noqa: F401,F403


def test_three_stage_task_pool_can_buffer_raw_detail_between_independent_workers(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001"])
    raw_output_dir = tmp_path / "detail_worker_2"
    analysis_output_dir = tmp_path / "detail_analysis_worker_3"

    def _capture_raw_detail(_http, seed, _browser_pages, *, config):
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        (item_dir / "detail.html").write_text("<html>buffered raw detail</html>", encoding="utf-8")
        (item_dir / "description-data.json").write_text('{"text":"buffered page text"}', encoding="utf-8")
        (item_dir / "selected.json").write_text('{"fetch":{"method":"raw-only"}}', encoding="utf-8")
        return {"item_id": str(seed["id"]), "detail_capture_mode": "raw"}

    raw_summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=raw_output_dir,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-2",
            do_risk=False,
            raw_only=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_capture_raw_detail,
    )

    assert raw_summary["decision"] == "detail_item_raw_captured"
    assert repo.seed_queue_counts()["seed_item_raw_detail_captured"] == 1

    def _analyze_buffered_raw(item_id: str, *, output_dir: Path, do_risk: bool) -> dict[str, object]:
        item_dir = output_dir / item_id
        assert item_dir == analysis_output_dir / "3001"
        assert (item_dir / "detail.html").read_text(encoding="utf-8") == "<html>buffered raw detail</html>"
        assert "buffered page text" in (item_dir / "description-data.json").read_text(encoding="utf-8")
        final = {
            "id": item_id,
            "title": "三段式任务池结果",
            "source_url": "https://sf-item.taobao.com/sf_item/3001.htm",
            "community_name": "任务池小区",
            "community_stable_key": "collector::广州市::南沙区::任务池小区",
            "city": "广州市",
            "district": "南沙区",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text(json.dumps({"item_id": item_id}, ensure_ascii=False), encoding="utf-8")
        return {"item_id": item_id, "do_risk": do_risk}

    analysis_summary = detail_worker.run_detail_analysis_once(
        detail_worker.DetailWorkerConfig(
            output_dir=analysis_output_dir,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="analysis-3",
            do_risk=False,
            analysis_only=True,
        ),
        repository=repo,
        analyze_item_func=_analyze_buffered_raw,
    )

    counts = repo.seed_queue_counts()
    assert analysis_summary["decision"] == "detail_analysis_completed"
    assert analysis_summary["staged_raw_artifacts"]["detail_html_path"] == str(
        analysis_output_dir / "3001" / "detail.html"
    )
    assert counts["seed_item_raw_detail_captured"] == 0
    assert counts["seed_item_detail_completed"] == 1
    assert repo.get_flat_item("3001")["community_stable_key"] == "collector::广州市::南沙区::任务池小区"

def test_llm_preflight_allows_missing_models_endpoint_when_chat_succeeds() -> None:
    assert detail_worker._llm_preflight_is_unavailable(
        {
            "enabled": True,
            "status_code": 404,
            "chat_status_code": 200,
        }
    ) is False

def test_run_detail_worker_batch_aborts_before_claiming_items_when_llm_chat_is_forbidden(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001"])
    processed: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed.append(str(seed["id"]))
        return {}

    def _preflight_llm_backend(*, timeout: float, check_chat: bool = False) -> dict[str, object]:
        return {
            "enabled": True,
            "url": "http://llm.local/v1/models",
            "status_code": 200,
            "chat_url": "http://llm.local/v1/chat/completions",
            "chat_status_code": 403,
        }

    monkeypatch.setattr(detail_worker, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=3,
            worker_id="detail-test",
            do_risk=False,
            llm_preflight_enabled=True,
            llm_preflight_timeout_seconds=2.5,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_worker_llm_unavailable"
    assert summary["attempts"] == 0
    assert summary["completed"] == 0
    assert summary["results"] == []
    assert summary["llm_preflight"]["chat_status_code"] == 403
    assert processed == []
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 1

def test_run_detail_worker_batch_aborts_before_claiming_items_when_llm_preflight_raises(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001"])
    processed: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed.append(str(seed["id"]))
        return {}

    preflight_calls: list[dict[str, object]] = []

    def _preflight_llm_backend(*, timeout: float, check_chat: bool = False) -> dict[str, object]:
        preflight_calls.append({"timeout": timeout, "check_chat": check_chat})
        raise RuntimeError("llm preflight connect timeout")

    monkeypatch.setattr(detail_worker, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=3,
            worker_id="detail-test",
            do_risk=False,
            llm_preflight_enabled=True,
            llm_preflight_timeout_seconds=2.5,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_worker_llm_unavailable"
    assert summary["attempts"] == 0
    assert summary["completed"] == 0
    assert summary["results"] == []
    assert summary["llm_preflight"]["error"] == "RuntimeError: runtime_error"
    assert summary["llm_preflight"]["attempt"] == 3
    assert preflight_calls == [{"timeout": 2.5, "check_chat": True}] * 3
    assert processed == []
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 1

def test_run_detail_worker_once_exits_cleanly_when_queue_is_empty(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
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
        process_item_func=lambda *_args, **_kwargs: {},
    )

    assert summary == {"decision": "detail_queue_empty"}

def test_run_detail_worker_loop_refreshes_runtime_context_each_batch(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    contexts: list[tuple[str, dict[str, tuple[str, str]]]] = []
    batches: list[tuple[str, dict[str, tuple[str, str]]]] = []

    def _runtime_context_factory():
        run = len(contexts) + 1
        context = (f"http-{run}", {"page": (f"title-{run}", f"url-{run}")})
        contexts.append(context)
        return context

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        batches.append((http_session, browser_pages))
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 0,
            "completed": 0,
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=1,
            max_runs=2,
        ),
        repository=repo,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=lambda _event: None,
    )

    assert summary["decision"] == "detail_worker_loop_finished"
    assert len(contexts) == 2
    assert batches == contexts

def test_run_detail_worker_loop_releases_existing_worker_leases_once_per_process(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    release_calls: list[str] = []

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        return {
            "decision": "detail_queue_empty",
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        repo,
        "release_seed_detail_worker_leases",
        lambda worker_id: release_calls.append(worker_id) or {"released": 1},
    )

    detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=1,
            max_runs=1,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        progress_emit_func=lambda _event: None,
    )

    assert release_calls == ["detail-test"]

def test_run_detail_worker_loop_emits_compact_batch_and_sleep_events(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 2,
            "completed": 1,
            "target_success": 3,
            "max_attempts": 4,
            "results": [
                {"decision": "detail_item_completed", "item_id": "3001"},
            ],
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=3,
            max_attempts=4,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=7,
            max_runs=2,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        progress_emit_func=events.append,
    )

    assert sleep_calls == [7]
    assert [event["event"] for event in events] == [
        "detail_worker_batch",
        "detail_worker_sleep",
        "detail_worker_batch",
    ]
    assert events[0]["run"] == 1
    assert events[0]["decision"] == "detail_worker_batch_finished"
    assert events[0]["completed"] == 1
    assert events[0]["last_result_decision"] == "detail_item_completed"
    assert events[0]["last_item_id"] == "3001"
    assert events[1] == {
        "event": "detail_worker_sleep",
        "run": 1,
        "sleep_seconds": 7,
        "counts": events[0]["counts"],
    }

def test_run_detail_worker_loop_uses_active_sleep_after_productive_batch(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 2,
            "completed": 2,
            "target_success": 3,
            "max_attempts": 4,
            "results": [
                {"decision": "detail_item_raw_captured", "item_id": "3001"},
                {"decision": "detail_item_raw_captured", "item_id": "3002"},
            ],
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=3,
            max_attempts=4,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=7,
            active_loop_interval_seconds=0,
            max_runs=2,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        progress_emit_func=events.append,
    )

    assert sleep_calls == [0]
    assert events[1] == {
        "event": "detail_worker_sleep",
        "run": 1,
        "sleep_seconds": 0,
        "counts": events[0]["counts"],
    }

def test_run_detail_worker_loop_keeps_idle_sleep_when_llm_unavailable(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    sleep_calls: list[int] = []

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        return {
            "decision": "detail_worker_llm_unavailable",
            "attempts": 0,
            "completed": 0,
            "target_success": 3,
            "max_attempts": 4,
            "results": [],
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=3,
            max_attempts=4,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=7,
            active_loop_interval_seconds=0,
            max_runs=2,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        progress_emit_func=lambda _event: None,
    )

    assert sleep_calls == [7]
