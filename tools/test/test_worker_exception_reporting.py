"""Failure reporting preserves worker decisions without persisting secrets."""

import json
import shlex
from dataclasses import replace
from unittest.mock import Mock

import pytest

from src.storage.models import CollectionSeedScanProgress, FapaiSeedItem
from tools import detail_worker, seed_collector
from tools.live_smoke_context import CdpEndpointUnavailableError
from tools.test.detail_worker_test_context import _make_repo, _seed_one_item
from tools.test.seed_collector_test_context import _FakeProbe

pytestmark = pytest.mark.security
PRIVATE = "synthetic-private-token"
ENDPOINT = f"https://user:{PRIVATE}@private.invalid/?token={PRIVATE}"


def _detail_config(tmp_path):
    return detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://127.0.0.1:9223",
        target_success=1,
        max_attempts=1,
        worker_id="synthetic-worker",
        do_risk=False,
        max_runs=1,
    )


def _seed_config(tmp_path):
    return seed_collector.SeedCollectorConfig(
        job_key="synthetic-job",
        province="广东省",
        city="广州市",
        district="南沙区",
        location_code="440115",
        category="50025969",
        sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
        max_page=1,
        cdp_endpoint="http://127.0.0.1:9223",
        output_dir=tmp_path,
        worker_id="synthetic-worker",
        max_runs=1,
    )


def _assert_safe_artifacts(tmp_path, summary):
    assert PRIVATE not in json.dumps(summary)
    for path in tmp_path.rglob("*.json"):
        assert PRIVATE not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("kind", ["seed", "detail"])
def test_configured_endpoint_credentials_are_absent_from_failure_hints(tmp_path, kind):
    config = replace(
        _seed_config(tmp_path) if kind == "seed" else _detail_config(tmp_path),
        cdp_endpoint=ENDPOINT + "#" + PRIVATE,
    )
    build = (
        seed_collector._build_cdp_unreachable_auth_probe
        if kind == "seed"
        else detail_worker._build_cdp_unreachable_health
    )
    result = build(config, "https://sf.taobao.com/list/50025969__2.htm")
    assert config.cdp_endpoint == ENDPOINT + "#" + PRIVATE
    assert result["cdp_endpoint"] == "https://private.invalid"
    assert result["cdp_endpoint_redacted"] is True
    assert PRIVATE not in json.dumps(result)
    assert "user:" not in json.dumps(result)
    command = shlex.split(result["operator_hint"]["helper_command"])
    assert command[command.index("--cdp-endpoint") + 1] == result["cdp_endpoint"]
    assert "parameters were omitted" in result["operator_hint"]["message"]
    if kind == "seed":
        assert result["attempted"] is True


def test_captcha_post_error_cannot_pass_raw_text_through_return_value(monkeypatch):
    from tools import taobao_login_health

    def fail(*args, **kwargs):
        raise OSError(ENDPOINT)

    monkeypatch.setattr(taobao_login_health, "post_json", fail)
    result = taobao_login_health.report_captcha_via_api(
        "https://api.invalid", ENDPOINT, "https://sf.taobao.com/list/50025969__2.htm"
    )
    assert result == {"status": "request_failed", "error": "OSError: io_error"}
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize(
    "error,reason,preserved",
    [
        (RuntimeError(ENDPOINT), "exception", False),
        (RuntimeError("anti-bot challenge " + ENDPOINT), "detail_challenge_page", True),
        (OSError("getaddrinfo failed " + ENDPOINT), "transient_dns_error", True),
        (
            CdpEndpointUnavailableError(ENDPOINT, PRIVATE, TimeoutError(PRIVATE)),
            "detail_cdp_unreachable",
            True,
        ),
        (
            CdpEndpointUnavailableError(
                ENDPOINT, "connect", OSError("getaddrinfo failed " + PRIVATE)
            ),
            "transient_dns_error",
            True,
        ),
    ],
)
def test_detail_failure_keeps_retry_budget_and_sanitizes_persistence(
    tmp_path, error, reason, preserved
):
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    def fail(*_args, **_kwargs):
        raise error from ValueError(PRIVATE)

    result = detail_worker.run_detail_worker_once(
        _detail_config(tmp_path),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=fail,
    )
    assert result["reason"] == reason
    assert bool(result.get("retry_budget_preserved")) is preserved
    assert "tools/detail_worker_execution.py:" in result["traceback"]
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert PRIVATE not in row.detail_last_error
        assert row.detail_attempt_count == (0 if preserved else 1)
        assert row.status == ("pending_detail" if preserved else "detail_failed")
    _assert_safe_artifacts(tmp_path, result)


@pytest.mark.parametrize("cdp_failure", [True, False])
def test_seed_failure_requeues_and_sanitizes_summary(
    tmp_path, monkeypatch, cdp_failure
):
    repo = _make_repo(tmp_path)

    def fail(*_args, **_kwargs):
        cause = TimeoutError(ENDPOINT)
        error = (
            CdpEndpointUnavailableError(ENDPOINT, PRIVATE, cause)
            if cdp_failure
            else cause
        )
        raise error from ValueError(PRIVATE)

    monkeypatch.setattr(seed_collector, "resolve_runtime_user_agent", lambda _: "test")
    monkeypatch.setattr(seed_collector, "fetch_list_page", fail)
    result = seed_collector.run_seed_collector_once(
        _seed_config(tmp_path),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )
    assert result["reason"] == ("cdp_unreachable" if cdp_failure else "exception")
    assert "tools/seed_collector_cycle.py:" in result["traceback"]
    with repo.session_factory() as session:
        row = session.get(CollectionSeedScanProgress, result["task"]["progress_key"])
        assert PRIVATE not in row.last_error
        assert row.last_error == result["error"]
    task = repo.claim_seed_scan_page("retry-worker", lease_seconds=30)
    assert task is not None and task["page"] == 1
    _assert_safe_artifacts(tmp_path, result)


@pytest.mark.parametrize("worker", ["seed", "detail"])
def test_runtime_refresh_reports_safe_error(tmp_path, monkeypatch, worker):
    module = seed_collector if worker == "seed" else detail_worker
    config = _seed_config(tmp_path) if worker == "seed" else _detail_config(tmp_path)
    repo = _make_repo(tmp_path)
    events = []
    if worker == "seed":
        monkeypatch.setattr(module, "_has_seed_scan_work", lambda _: (True, {}))

    def fail():
        raise RuntimeError(ENDPOINT) from ValueError(PRIVATE)

    kwargs = {"browserless_seed_probe": _FakeProbe} if worker == "seed" else {}
    runner = (
        module.run_seed_collector_loop
        if worker == "seed"
        else module.run_detail_worker_loop
    )
    result = runner(
        config,
        repository=repo,
        runtime_context_factory=fail,
        progress_emit_func=events.append,
        **kwargs,
    )
    assert any(event.get("error") == "RuntimeError: runtime_error" for event in events)
    _assert_safe_artifacts(tmp_path, [result, events])


@pytest.mark.parametrize("backend_unavailable", [True, False])
def test_analysis_failure_keeps_backend_retry_flags_without_provider_text(
    tmp_path, monkeypatch, backend_unavailable
):
    repository = Mock()
    repository.claim_seed_raw_detail_item.return_value = {"item_id": "synthetic-item"}
    repository.seed_queue_counts.return_value = {}
    monkeypatch.setattr(
        detail_worker, "_stage_raw_detail_artifacts_for_analysis", lambda *a, **k: {}
    )

    def fail(*_args, **_kwargs):
        message = "LLM backend unavailable " if backend_unavailable else "failure "
        raise RuntimeError(message + ENDPOINT) from ValueError(PRIVATE)

    result = detail_worker.run_detail_analysis_once(
        _detail_config(tmp_path), repository=repository, analyze_item_func=fail
    )
    expected = "backend_unavailable" if backend_unavailable else "retryable_failure"
    assert result["decision"] == "detail_analysis_" + expected
    call = repository.mark_seed_detail_analysis_failed.call_args
    assert PRIVATE not in call.args[1]
    assert call.kwargs["retryable"] is True
    assert bool(call.kwargs.get("revert_attempt")) is backend_unavailable
    assert bool(call.kwargs.get("restore_raw")) is backend_unavailable
    _assert_safe_artifacts(tmp_path, result)


def test_preflight_and_receipt_persistence_errors_are_safe(
    tmp_path, monkeypatch, capsys
):
    def fail(*_args, **_kwargs):
        raise RuntimeError(ENDPOINT) from ValueError(PRIVATE)

    monkeypatch.setattr(detail_worker, "preflight_llm_backend", fail)
    result = detail_worker._run_llm_preflight(
        replace(_detail_config(tmp_path), llm_preflight_attempts=1)
    )
    assert result["error"] == "RuntimeError: runtime_error"
    repository = Mock(record_analysis_ensemble_run=Mock(side_effect=fail))
    detail_worker._record_analysis_module_b_receipt(
        repository, item_id="synthetic-item", receipt={"run_id": "synthetic-run"}
    )
    assert PRIVATE not in capsys.readouterr().out
