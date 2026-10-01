"""An exploratory model failure must not stop already qualified business routes."""
import time

import pytest
import requests

from src.llm_model_selector import LLMBackendUnavailableError
from src.llm_qualification_store import QualificationStore
from tools.test.test_llm_qualification_pool import Response, make_pool


def ready_pool(tmp_path):
    pool = make_pool(tmp_path, {"good": 5})
    assert pool.ensure() == ["good"]
    pool.session.models["candidate"] = 5
    pool.store.change(lambda state: state.update(next_scan=0, scan_complete=False))
    return pool


def fail_exploration(pool, phase, failure, calls):
    original = pool.session.post

    def unavailable(*args, **kwargs):
        if phase == "candidate" and kwargs["json"]["model"] == "good":
            return original(*args, **kwargs)
        calls.append(phase)
        if failure == "timeout":
            raise requests.ReadTimeout("fixture timeout")
        response = Response({"choices": []} if phase == "candidate" else {"data": None})
        if isinstance(failure, int):
            response.status_code = failure
            if failure in {401, 403, 429}:
                response.headers = {"Retry-After": "7200"}
        return response

    if phase == "catalog":
        pool.session.get = unavailable
    else:
        pool.session.post = unavailable


@pytest.mark.parametrize("phase", ["catalog", "candidate"])
@pytest.mark.parametrize("failure", ["timeout", "invalid_response", 400, 503])
def test_failed_exploration_defers_scan_but_keeps_qualified_business(tmp_path, phase, failure):
    pool = ready_pool(tmp_path)
    qualified_before = pool.store.snapshot()["models"]["good"]
    calls = []
    fail_exploration(pool, phase, failure, calls)

    assert pool.ensure() == ["good"]
    state = pool.store.snapshot()
    assert state["models"]["good"] == qualified_before
    assert state["next_scan"] > time.time() + 590
    assert not state.get("cooldown_until")
    assert calls == [phase]
    assert pool.chat("real item") == "production"

    peer = make_pool(tmp_path, {"good": 5, "candidate": 5})
    assert peer.refresh_in_background() == ["good"]
    assert peer.ensure() == ["good"]
    assert not peer.session.calls
    assert peer.chat("another item") == "production"
    assert pool.ensure() == ["good"]
    assert calls == [phase]


@pytest.mark.parametrize("phase", ["catalog", "candidate"])
@pytest.mark.parametrize("status", [401, 403, 429])
def test_account_rejection_still_blocks_qualified_routes_across_workers(tmp_path, phase, status):
    pool = ready_pool(tmp_path)
    qualified_before = pool.store.snapshot()["models"]["good"]
    calls = []
    fail_exploration(pool, phase, status, calls)

    assert pool.ensure() == []
    state = pool.store.snapshot()
    assert state["models"]["good"] == qualified_before
    assert state["cooldown_until"] > time.time() + 7190
    assert state["next_scan"] >= state["cooldown_until"]
    peer = make_pool(tmp_path, {"good": 5})
    assert peer.available() == []
    assert QualificationStore.reserve_request_slot(peer.store) is None
    with pytest.raises(LLMBackendUnavailableError):
        peer.chat("real item")
    assert not peer.session.calls
    assert calls == [phase]


@pytest.mark.parametrize("unavailable", ["expired", "blocked"])
def test_unusable_old_qualification_does_not_keep_business_open(tmp_path, unavailable):
    pool = ready_pool(tmp_path)

    def invalidate(state):
        row = state["models"]["good"]
        if unavailable == "expired":
            row["checked_at"] = time.time() - 86401
        else:
            row["blocked_until"] = time.time() + 900

    pool.store.change(invalidate)
    calls = []
    phase = "renewal" if unavailable == "expired" else "candidate"
    fail_exploration(pool, phase, "timeout", calls)
    assert pool.ensure() == []
    assert pool.store.snapshot()["cooldown_until"] > time.time() + 590
    assert calls == [phase]
    if unavailable == "expired":
        assert pool.store.snapshot()["models"]["good"]["score"] is None


def test_scan_backoff_preserves_shared_business_request_spacing(tmp_path, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    config = {"base_url": "https://models.example.test/v1", "api_key": "fixture"}
    first = QualificationStore(config, tmp_path / "pool.sqlite3")
    second = QualificationStore(config, tmp_path / "pool.sqlite3")
    assert first.reserve_request_slot() == 0
    first.defer_scan(600)
    assert not second.claim()
    assert second.reserve_request_slot() == 4
    now[0] += 4
    assert second.reserve_request_slot() == 0
    assert first.reserve_request_slot() == 4
