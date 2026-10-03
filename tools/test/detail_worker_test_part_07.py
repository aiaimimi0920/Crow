from tools.test.detail_worker_test_context import *  # noqa: F401,F403


def test_run_detail_worker_loop_retries_after_runtime_context_refresh_failure(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    contexts: list[str] = []

    def _runtime_context_factory():
        if not contexts:
            contexts.append("failed")
            raise RuntimeError("cdp unavailable")
        contexts.append("ok")
        return "http-ok", {}

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 0,
            "completed": 0,
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    summary = detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=5,
            max_runs=2,
        ),
        repository=repo,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=events.append,
    )

    assert contexts == ["failed", "ok"]
    assert sleep_calls == [5]
    assert [event["event"] for event in events] == [
        "detail_worker_runtime_refresh_failed",
        "detail_worker_sleep",
        "detail_worker_batch",
    ]
    assert events[0]["run"] == 1
    assert events[0]["decision"] == "detail_runtime_refresh_failed"
    assert events[0]["error"] == "RuntimeError: runtime_error"
    assert summary["runs"] == 2
    assert summary["last_decision"] == "detail_worker_batch_finished"

def test_run_detail_worker_loop_reuses_last_runtime_context_after_later_refresh_failure(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    used_batches: list[tuple[str, dict[str, tuple[str, str]]]] = []
    calls = {"count": 0}

    def _runtime_context_factory():
        calls["count"] += 1
        if calls["count"] == 1:
            return "http-1", {"page": ("title-1", "url-1")}
        raise RuntimeError("cdp refresh timed out")

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        used_batches.append((http_session, browser_pages))
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 0,
            "completed": 0,
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    summary = detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=5,
            max_runs=2,
        ),
        repository=repo,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=events.append,
    )

    assert used_batches == [
        ("http-1", {"page": ("title-1", "url-1")}),
        ("http-1", {"page": ("title-1", "url-1")}),
    ]
    assert sleep_calls == [5]
    assert [event["event"] for event in events] == [
        "detail_worker_batch",
        "detail_worker_sleep",
        "detail_worker_runtime_refresh_reused_last_context",
        "detail_worker_batch",
    ]
    assert events[2]["run"] == 2
    assert events[2]["error"] == "RuntimeError: runtime_error"
    assert summary["runs"] == 2
    assert summary["last_decision"] == "detail_worker_batch_finished"
