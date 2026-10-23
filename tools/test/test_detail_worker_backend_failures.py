"""Global AI failures preserve item budget; invalid item requests do not."""

import json
from unittest.mock import Mock

import pytest
import requests

from src.llm_backend_failures import is_backend_http_failure
from tools import detail_worker


def http_error(status, body=None):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body or {}).encode()
    return requests.HTTPError("synthetic upstream HTTP failure", response=response)


@pytest.mark.parametrize(
    "error",
    [
        http_error(
            400, {"error": {"message": "credit insufficient balance: balance=0"}}
        ),
        http_error(400, {"error": {"code": "insufficient_user_quota"}}),
        *[http_error(code) for code in (401, 403, 404, 408, 425, 429, 500, 503, 599)],
        requests.ConnectionError("synthetic connection failure"),
        requests.Timeout("synthetic timeout"),
    ],
)
def test_global_failure_restores_raw_item_and_retry_budget(
    tmp_path, monkeypatch, error
):
    repository = Mock()
    repository.claim_seed_raw_detail_item.return_value = {"item_id": "123"}
    repository.seed_queue_counts.return_value = {}
    monkeypatch.setattr(
        detail_worker, "_stage_raw_detail_artifacts_for_analysis", lambda *a, **k: {}
    )
    config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://127.0.0.1:9223",
        worker_id="backend-fixture",
        target_success=1,
        max_attempts=1,
        do_risk=False,
    )

    def analyze(*_args, **_kwargs):
        raise error

    result = detail_worker.run_detail_analysis_once(
        config,
        repository=repository,
        analyze_item_func=analyze,
    )
    assert result["decision"] == "detail_analysis_backend_unavailable"
    flags = repository.mark_seed_detail_analysis_failed.call_args.kwargs
    assert flags == {"retryable": True, "revert_attempt": True, "restore_raw": True}
    repository.mark_seed_detail_completed.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        http_error(400, {"error": {"message": "invalid input"}}),
        http_error(400, {"message": "insufficient_quota"}),
        http_error(400, {"error": {"message": "insufficient_quota" + "x" * 8192}}),
        http_error(422),
        requests.HTTPError("no response"),
        ValueError("invalid artifact"),
    ],
)
def test_unrelated_or_unstructured_errors_remain_item_failures(error):
    assert not is_backend_http_failure(error)


def test_malformed_quota_body_is_not_backend_evidence():
    error = http_error(400)
    for body in (b"not-json", b"\xff", b"[]", b'{"error":null}'):
        error.response._content = body
        assert not is_backend_http_failure(error)
