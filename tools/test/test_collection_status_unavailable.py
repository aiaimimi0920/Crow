"""Unknown control state must not authorize collection or authentication probes."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from tools import (
    detail_worker,
    detail_worker_policy,
    seed_collector,
    seed_collector_auth,
)

READERS = [detail_worker, detail_worker_policy, seed_collector, seed_collector_auth]
API = "https://control.invalid/api"


def unavailable(kind):
    if kind == "timeout":
        raise TimeoutError("PRIVATE_CONTROL_ENDPOINT")
    if kind == "connection":
        raise URLError("PRIVATE_CONTROL_ENDPOINT")
    if kind in {"401", "403"}:
        raise HTTPError(API, int(kind), "PRIVATE_CONTROL_ENDPOINT", {}, None)
    if kind == "json":
        raise json.JSONDecodeError("invalid", "PRIVATE_CONTROL_BODY", 0)
    return ["PRIVATE_CONTROL_BODY"]


@pytest.mark.parametrize("owner", READERS)
@pytest.mark.parametrize(
    "kind", ["timeout", "connection", "401", "403", "json", "list"]
)
def test_status_read_failure_is_paused_not_permission(owner, kind, monkeypatch):
    monkeypatch.setattr(owner, "fetch_json", lambda *a, **kw: unavailable(kind))
    result = owner._collection_pause_state(API)
    assert result["paused"] is True
    assert result["reason"] == "status_unavailable"
    assert not result.get("captcha_solver")


@pytest.mark.parametrize("owner", [detail_worker, seed_collector])
@pytest.mark.parametrize("kind", ["timeout", "401", "list"])
def test_exhausted_status_retries_prevent_claim_fetch_and_auth_probe(
    owner, kind, tmp_path, monkeypatch
):
    reads, sleeps = [], []

    def fetch(url, *, timeout):
        reads.append((url, timeout))
        return unavailable(kind)

    monkeypatch.setattr(owner, "fetch_json", fetch)
    monkeypatch.setattr(owner.time, "sleep", sleeps.append)
    repository = Mock()
    repository.seed_queue_counts.return_value = {}
    action = Mock(side_effect=AssertionError("unknown status must not start work"))
    if owner is detail_worker:
        config = owner.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="",
            worker_id="test",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            api_base_url=API,
        )
        result = owner.run_detail_worker_once(
            config,
            repository=repository,
            http_session=None,
            browser_pages={},
            process_item_func=action,
        )
        repository.claim_seed_detail_item.assert_not_called()
        assert result["claimed_items"] == result["process_item_calls"] == 0
        assert result["paused_results"] == 1
        decision = "detail_collection_paused"
    else:
        monkeypatch.setattr(owner, "_probe_seed_auth_state", action)
        monkeypatch.setattr(owner, "_ensure_seed_scan_jobs", action)
        config = SimpleNamespace(output_dir=tmp_path, api_base_url=API)
        result = owner.run_seed_collector_once(
            config,
            repository=repository,
            http_session=None,
            browserless_seed_probe=None,
        )
        repository.claim_seed_scan_page.assert_not_called()
        decision = "seed_collection_paused"
    assert result["decision"] == decision
    assert result["reason"] == "status_unavailable"
    assert reads == [(API + "/status", 5)] * owner.STATUS_UNAVAILABLE_RETRY_ATTEMPTS
    assert sleeps == [owner.STATUS_UNAVAILABLE_RETRY_SLEEP_SECONDS] * (len(reads) - 1)
    action.assert_not_called()
    repository.mark_seed_detail_failed.assert_not_called()


@pytest.mark.parametrize("owner", READERS)
@pytest.mark.parametrize("paused", [False, True])
def test_existing_retry_can_recover_to_actual_control_state(owner, paused, monkeypatch):
    replies = iter([None, {"paused": paused, "captcha_solver": {}}])
    reads, sleeps = [], []

    def fetch(*args, **kwargs):
        reads.append(True)
        reply = next(replies)
        if reply is None:
            raise TimeoutError()
        return reply

    monkeypatch.setattr(owner, "fetch_json", fetch)
    monkeypatch.setattr(owner.time, "sleep", sleeps.append)
    result = owner._collection_pause_state_with_retry(API)
    assert result["paused"] is paused
    assert result.get("reason") != "status_unavailable"
    assert len(reads) == 2 and sleeps == [1.0]


@pytest.mark.parametrize("owner", READERS)
def test_explicit_standalone_mode_does_not_require_control_api(owner, monkeypatch):
    unexpected = Mock(
        side_effect=AssertionError("standalone mode must not query status")
    )
    monkeypatch.setattr(owner, "fetch_json", unexpected)
    assert owner._collection_pause_state_with_retry("") == {
        "paused": False,
        "reason": "status_probe_disabled",
    }
    unexpected.assert_not_called()


def test_unknown_control_state_has_its_own_safe_batch_category():
    from tools.detail_worker_observation import batch_observation, item_observation

    result = {
        **item_observation(),
        "decision": "detail_collection_paused",
        "reason": "status_unavailable",
        "paused_results": 1,
    }
    observed = batch_observation([result], elapsed_seconds=1)
    assert observed["reason_counts"] == {"status_unavailable": 1}
    assert observed["claimed_items"] == observed["process_item_calls"] == 0
