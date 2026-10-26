"""Exact item boundaries and bounded telemetry without business-text keys."""

from dataclasses import replace
from unittest.mock import Mock

import pytest

from tools import detail_worker
from tools.detail_worker_observation import batch_observation, item_observation


def test_batch_aggregation_does_not_infer_requests_or_expand_log_categories():
    result = batch_observation(
        [
            {
                **item_observation(),
                "claimed_items": 1,
                "process_item_calls": 1,
                "decision": "detail_item_completed",
            },
            {
                **item_observation(),
                "claimed_items": 1,
                "process_item_calls": 1,
                "decision": "detail_item_retryable_failure",
                "reason": "transient_dns_error",
            },
            {
                **item_observation(),
                "paused_results": 1,
                "decision": "detail_collection_paused",
                "reason": "operator_paused",
            },
            {
                "decision": "https://private.invalid/business",
                "reason": ["private prompt"],
                "error": "private response",
                "claimed_items": True,
            },
        ],
        elapsed_seconds=12.3456,
    )
    assert result["claimed_items"] == result["process_item_calls"] == 2
    assert result["analysis_item_calls"] == 0
    assert result["paused_results"] == 1
    assert result["page_requests"] is None
    assert result["page_requests_observed"] is False
    assert result["batch_elapsed_seconds"] == 12.346
    assert result["item_observation_missing"] == 1
    assert result["reason_counts"] == {
        "transient_dns_error": 1,
        "operator_paused": 1,
        "other": 1,
    }
    assert result["decision_counts"]["other"] == 1
    assert "private" not in str(result)


@pytest.mark.parametrize("elapsed", [None, "private", float("nan"), float("inf")])
def test_old_or_invalid_observation_is_unknown_not_inferred_from_item_id(elapsed):
    result = batch_observation(
        [
            {"decision": "detail_item_completed", "item_id": "123"},
            {**item_observation(), "claimed_items": 9},
        ],
        elapsed_seconds=elapsed,
    )
    assert result["claimed_items"] == 0
    assert result["item_observation_missing"] == 2
    assert result["batch_elapsed_seconds"] is None


@pytest.fixture
def worker(tmp_path, monkeypatch):
    config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="",
        target_success=1,
        max_attempts=1,
        worker_id="observation-fixture",
        do_risk=False,
    )
    repo = Mock()
    seed = {"item_id": "123", "url": "https://example.invalid/123"}
    repo.claim_seed_detail_item.return_value = seed
    repo.claim_seed_raw_detail_item.return_value = seed
    repo.seed_queue_counts.return_value = {}
    monkeypatch.setattr(
        detail_worker, "_collection_pause_state_with_retry", lambda _: {}
    )
    monkeypatch.setattr(
        detail_worker, "_detail_seed_target_url", lambda *a, **k: seed["url"]
    )
    monkeypatch.setattr(detail_worker, "_live_config", lambda *a, **k: object())
    monkeypatch.setattr(
        detail_worker, "_stage_raw_detail_artifacts_for_analysis", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        detail_worker, "_load_analysis_module_b_latest", lambda *a: None
    )
    return config, repo


def execute(worker, stage, process):
    config, repo = worker
    if stage == "analysis":
        return detail_worker.run_detail_analysis_once(
            config, repository=repo, analyze_item_func=process
        )
    return detail_worker.run_detail_worker_once(
        config,
        repository=repo,
        http_session=None,
        browser_pages={},
        process_item_func=process,
    )


@pytest.mark.parametrize("stage", ["detail", "analysis"])
def test_empty_queue_records_zero_claims_and_calls(worker, stage):
    config, repo = worker
    repo.claim_seed_detail_item.return_value = None
    repo.claim_seed_raw_detail_item.return_value = None
    result = execute(
        worker, stage, lambda *a, **k: pytest.fail("empty queue must not execute")
    )
    assert {key: result[key] for key in item_observation()} == item_observation()


@pytest.mark.parametrize(
    "boundary,stage,calls",
    [
        ("target", "detail", 0),
        ("config", "detail", 0),
        ("staging", "analysis", 0),
        ("call", "detail", 1),
        ("call", "analysis", 1),
    ],
)
def test_call_counts_only_actual_function_entry(
    worker, monkeypatch, boundary, stage, calls
):
    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic failure")

    names = {
        "target": "_detail_seed_target_url",
        "config": "_live_config",
        "staging": "_stage_raw_detail_artifacts_for_analysis",
    }
    if boundary in names:
        monkeypatch.setattr(detail_worker, names[boundary], fail)
    process = Mock(side_effect=fail)
    result = execute(worker, stage, process)
    assert result["decision"].endswith("retryable_failure")
    assert result["claimed_items"] == 1
    assert result["paused_results"] == 0
    assert result["process_item_calls"] == (calls if stage == "detail" else 0)
    assert result["analysis_item_calls"] == (calls if stage == "analysis" else 0)
    assert process.call_count == calls


@pytest.mark.parametrize("stage", ["detail", "analysis"])
def test_success_records_claim_and_exact_processing_entry(worker, stage):
    config, repo = worker

    def process(*_args, **_kwargs):
        folder = config.output_dir / "123"
        folder.mkdir(exist_ok=True)
        (folder / "final.json").write_text('{"id":"123"}', encoding="utf-8")
        return {}

    result = execute(worker, stage, process)
    assert result["decision"].endswith("completed")
    assert result["claimed_items"] == 1
    assert result["process_item_calls"] == int(stage == "detail")
    assert result["analysis_item_calls"] == int(stage == "analysis")
    repo.mark_seed_detail_completed.assert_called_once()


def test_preflight_early_return_has_elapsed_and_zero_item_work(worker, monkeypatch):
    config, repo = worker
    clock = [10.0]
    monkeypatch.setattr(detail_worker.time, "monotonic", lambda: clock[0])

    def preflight(_config):
        clock[0] += 4
        return {"error": "synthetic unavailable"}

    monkeypatch.setattr(detail_worker, "_run_llm_preflight", preflight)
    result = detail_worker.run_detail_worker_batch(
        replace(config, llm_preflight_enabled=True),
        repository=repo,
        http_session=None,
        browser_pages={},
    )
    assert result["attempts"] == result["claimed_items"] == 0
    assert result["batch_elapsed_seconds"] == 4
    event = detail_worker._detail_batch_progress_event(1, result)
    assert event["batch_elapsed_seconds"] == 4
    assert event["reason_counts"] == event["decision_counts"] == {}
    assert event["page_requests"] is None
    repo.claim_seed_detail_item.assert_not_called()


def test_runtime_refresh_failure_also_emits_completed_wait(worker, monkeypatch):
    from tools import worker_lifecycle

    config, repo = worker
    del repo.release_seed_detail_worker_leases
    clock, events = [0.0], []
    monkeypatch.setattr(detail_worker.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(worker_lifecycle, "checkpoint", lambda _: True)
    monkeypatch.setattr(
        worker_lifecycle,
        "wait",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )

    def fail():
        raise RuntimeError("synthetic refresh failure")

    detail_worker.run_detail_worker_loop(
        replace(config, max_runs=2, loop_interval_seconds=7),
        repository=repo,
        runtime_context_factory=fail,
        progress_emit_func=events.append,
    )
    receipt = next(
        event for event in events if event["event"] == "detail_worker_wait_finished"
    )
    assert receipt == {
        "event": "detail_worker_wait_finished",
        "run": 1,
        "requested_wait_seconds": 7,
        "actual_wait_seconds": 7,
        "status_poll_count": 0,
        "wait_exit": "wait_returned",
    }
