from tools.test.seed_collector_test_context import *  # noqa: F401,F403


def test_run_seed_collector_loop_emits_compact_run_and_sleep_events(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    run_results = iter(
        [
            {"decision": "seed_page_collected", "item_count": 2, "has_next": True, "counts": {"seed_item_pending_detail": 2}},
            {"decision": "seed_scan_queue_empty", "counts": {"seed_item_pending_detail": 2}},
            {"decision": "seed_scan_queue_empty", "counts": {"seed_item_pending_detail": 2}},
        ]
    )

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", lambda *_args, **_kwargs: next(run_results))
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    seed_collector.run_seed_collector_loop(
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
            loop_interval_seconds=7,
            max_runs=2,
            pages_per_run=2,
            page_delay_seconds=0,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
        progress_emit_func=events.append,
    )

    assert sleep_calls == [7]
    assert [event["event"] for event in events] == [
        "seed_collector_run",
        "seed_collector_sleep",
        "seed_collector_run",
    ]
    assert events[0]["run"] == 1
    assert events[0]["pages_attempted"] == 1
    assert events[0]["last_decision"] == "seed_scan_queue_empty"
    assert events[0]["last_item_count"] is None
    assert events[1] == {
        "event": "seed_collector_sleep",
        "run": 1,
        "sleep_seconds": 7,
        "counts": events[0]["counts"],
    }

def test_seed_run_progress_event_includes_operator_cycle_summary() -> None:
    event = seed_collector._seed_run_progress_event(
        7,
        [
            {
                "decision": "seed_page_collected",
                "item_count": 60,
                "upsert": {"seen": 60, "new_items": 30, "existing_items": 30, "new_occurrences": 60},
                "counts": {"seed_occurrence_total": 100},
            },
            {
                "decision": "seed_page_retryable_failure",
                "reason": "list_challenge_page",
                "counts": {"seed_occurrence_total": 100},
            },
            {
                "decision": "seed_scan_queue_empty",
                "counts": {"seed_occurrence_total": 100},
            },
        ],
    )

    assert event["cycle_summary"] == {
        "pages_attempted": 2,
        "pages_collected": 1,
        "retryable_failures": 1,
        "paused_count": 0,
        "queue_empty_count": 1,
        "items_seen": 60,
        "items_collected": 60,
        "new_items": 30,
        "existing_items": 30,
        "new_occurrences": 60,
        "decision_counts": {
            "seed_page_collected": 1,
            "seed_page_retryable_failure": 1,
            "seed_scan_queue_empty": 1,
        },
    }
    assert event["pages_attempted"] == 2
    assert event["new_occurrences"] == 60
    assert event["last_reason"] is None

    retry_event = seed_collector._seed_run_progress_event(
        8,
        [{"decision": "seed_page_retryable_failure", "reason": "list_challenge_page", "counts": {"seed_occurrence_total": 100}}],
    )

    assert retry_event["last_reason"] == "list_challenge_page"

def test_seed_run_progress_event_surfaces_last_auth_probe_for_operator_visibility() -> None:
    event = seed_collector._seed_run_progress_event(
        9,
        [
            {
                "decision": "seed_collection_paused",
                "reason": "captcha_solver_manual_required",
                "auth_probe": {
                    "attempted": True,
                    "authenticated": False,
                    "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
                },
                "counts": {"seed_occurrence_total": 100},
            }
        ],
    )

    assert event["last_auth_probe"] == {
        "attempted": True,
        "authenticated": False,
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    }
    assert event["auth_probe_attempted"] is True

def test_run_seed_collector_loop_writes_partial_cycle_summary_after_each_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    written: list[dict[str, Any]] = []
    run_results = iter(
        [
            {
                "decision": "seed_page_collected",
                "item_count": 2,
                "upsert": {"seen": 2, "new_items": 2, "existing_items": 0, "new_occurrences": 2},
                "counts": {"seed_occurrence_total": 2},
            },
            {
                "decision": "seed_page_retryable_failure",
                "reason": "list_challenge_page",
                "counts": {"seed_occurrence_total": 2},
            },
        ]
    )
    monkeypatch.setattr(seed_collector, "_write_runtime_summary", lambda _output_dir, summary: written.append(dict(summary)))
    monkeypatch.setattr(seed_collector, "_ensure_seed_scan_jobs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(seed_collector, "run_seed_collector_once", lambda *_args, **_kwargs: next(run_results))

    class WorkRepository:
        def seed_queue_counts(self) -> dict[str, int]:
            return {"seed_scan_progress_pending": 1, "seed_scan_progress_in_progress": 0}

    seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="job-1",
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
            max_runs=1,
            pages_per_run=2,
        ),
        repository=WorkRepository(),  # type: ignore[arg-type]
        http_session=object(),
        browserless_seed_probe=object(),
    )

    partial_events = [summary for summary in written if summary.get("event") == "seed_collector_run_in_progress"]
    assert [event["cycle_summary"]["pages_attempted"] for event in partial_events] == [1, 2]
    assert partial_events[0]["cycle_summary"]["pages_collected"] == 1
    assert partial_events[1]["cycle_summary"]["retryable_failures"] == 1

def test_run_seed_collector_loop_uses_active_sleep_after_productive_run(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    run_results = iter(
        [
            {"decision": "seed_page_collected", "item_count": 2, "has_next": True, "counts": {"seed_item_pending_detail": 2}},
            {"decision": "seed_page_collected", "item_count": 1, "has_next": True, "counts": {"seed_item_pending_detail": 3}},
        ]
    )

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", lambda *_args, **_kwargs: next(run_results))
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    seed_collector.run_seed_collector_loop(
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
            loop_interval_seconds=7,
            active_loop_interval_seconds=0,
            max_runs=2,
            pages_per_run=1,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
        progress_emit_func=events.append,
    )

    assert sleep_calls == [0]
    assert events[1] == {
        "event": "seed_collector_sleep",
        "run": 1,
        "sleep_seconds": 0,
        "counts": events[0]["counts"],
    }

def test_run_seed_collector_loop_uses_auth_probe_sleep_after_challenge_page(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    sleep_calls: list[int] = []
    run_results = iter(
        [
            {"decision": "seed_page_retryable_failure", "reason": "list_challenge_page", "counts": {}},
            {"decision": "seed_page_collected", "item_count": 1, "has_next": True, "counts": {}},
        ]
    )

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", lambda *_args, **_kwargs: next(run_results))
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    seed_collector.run_seed_collector_loop(
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
            loop_interval_seconds=7,
            active_loop_interval_seconds=0,
            auth_probe_interval_seconds=3,
            max_runs=2,
            pages_per_run=1,
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
        progress_emit_func=lambda _event: None,
    )

    assert sleep_calls == [3]

def test_run_seed_collector_loop_retries_after_runtime_context_refresh_failure(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    contexts: list[str] = []

    def _runtime_context_factory() -> str:
        if not contexts:
            contexts.append("failed")
            raise RuntimeError("cdp unavailable")
        contexts.append("ok")
        return "http-ok"

    def _run_once(_config, *, repository, http_session, browserless_seed_probe, ensure_jobs=True):
        return {"decision": "seed_scan_queue_empty", "counts": repository.seed_queue_counts()}

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", _run_once)
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    summary = seed_collector.run_seed_collector_loop(
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
            loop_interval_seconds=5,
            max_runs=2,
            pages_per_run=2,
        ),
        repository=repo,
        browserless_seed_probe=_FakeProbe,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=events.append,
    )

    assert contexts == ["failed", "ok"]
    assert sleep_calls == [5]
    assert [event["event"] for event in events] == [
        "seed_collector_runtime_refresh_failed",
        "seed_collector_sleep",
        "seed_collector_run",
    ]
    assert events[0]["run"] == 1
    assert events[0]["decision"] == "seed_runtime_refresh_failed"
    assert events[0]["error"] == "RuntimeError: runtime_error"
    assert summary["runs"] == 2
    assert summary["last_decision"] == "seed_scan_queue_empty"

def test_run_seed_collector_loop_reuses_last_runtime_context_after_later_refresh_failure(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    used_sessions: list[str] = []
    calls = {"count": 0}

    def _runtime_context_factory() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            return "http-1"
        raise RuntimeError("cdp refresh timed out")

    def _run_once(_config, *, repository, http_session, browserless_seed_probe, ensure_jobs=True):
        used_sessions.append(http_session)
        return {"decision": "seed_scan_queue_empty", "counts": repository.seed_queue_counts()}

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", _run_once)
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    summary = seed_collector.run_seed_collector_loop(
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
            loop_interval_seconds=5,
            max_runs=2,
            pages_per_run=2,
        ),
        repository=repo,
        browserless_seed_probe=_FakeProbe,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=events.append,
    )

    assert used_sessions == ["http-1", "http-1"]
    assert sleep_calls == [5]
    assert [event["event"] for event in events] == [
        "seed_collector_run",
        "seed_collector_sleep",
        "seed_collector_runtime_refresh_reused_last_context",
        "seed_collector_run",
    ]
    assert events[2]["run"] == 2
    assert events[2]["error"] == "RuntimeError: runtime_error"
    assert summary["runs"] == 2
    assert summary["last_decision"] == "seed_scan_queue_empty"
