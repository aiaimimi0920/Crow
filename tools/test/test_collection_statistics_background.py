"""Slow telemetry must not serialize or delay fresh collection control reads."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from src import collection_statistics as owner
from src.collection_statistics import StatisticsCache


def finish(cache, release):
    release.set()
    thread = getattr(cache, "_refresh_thread", None)
    if thread is not None:
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_cold_background_cache_returns_unknown_without_waiting_for_database():
    cache = StatisticsCache()
    cache.background_refresh = True
    entered, release = Event(), Event()
    calls = []

    def load():
        calls.append(1)
        entered.set()
        assert release.wait(timeout=2)
        return {"seed_item_pending_detail": 7}

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(cache.snapshot, cache, load)
        try:
            assert entered.wait(timeout=1)
            result = pending.result(timeout=0.5)
            assert result["counts"] == {}
            assert result["metadata"]["valid"] is False
            assert result["metadata"]["refreshing"] is True
            for _ in range(20):
                assert cache.snapshot(cache, load)["metadata"]["refreshing"]
            assert calls == [1]
        finally:
            finish(cache, release)
    assert cache.snapshot(cache, load)["counts"] == {"seed_item_pending_detail": 7}


def test_expired_snapshot_is_returned_as_stale_while_refresh_is_single_flight():
    now = [0.0]
    cache = StatisticsCache(clock=lambda: now[0])
    identity = object()
    cache.snapshot(identity, lambda: {"seed_item_pending_detail": 2})
    cache.background_refresh = True
    now[0] = 15
    entered, release = Event(), Event()
    calls = []

    def load():
        calls.append(1)
        entered.set()
        assert release.wait(timeout=2)
        return {"seed_item_pending_detail": 9}

    try:
        result = cache.snapshot(identity, load)
        assert entered.wait(timeout=1)
        assert result["counts"]["seed_item_pending_detail"] == 2
        assert result["metadata"]["valid"] is True
        assert result["metadata"]["stale"] is True
        assert result["metadata"]["age_seconds"] == 15
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(
                executor.map(lambda _: cache.snapshot(identity, load), range(32))
            )
        assert all(r["metadata"]["refreshing"] for r in results)
        assert calls == [1]
    finally:
        finish(cache, release)
    result = cache.snapshot(identity, load)
    assert result["counts"]["seed_item_pending_detail"] == 9
    assert not result["metadata"]["stale"]
    assert not result["metadata"]["refreshing"]
    result["counts"].clear()
    assert cache.snapshot(identity, load)["counts"]["seed_item_pending_detail"] == 9


def test_background_failure_is_redacted_throttled_and_keeps_previous_counts():
    now = [0.0]
    cache = StatisticsCache(clock=lambda: now[0])
    cache.snapshot(cache, lambda: {"seed_item_pending_detail": 3})
    cache.background_refresh = True
    now[0] = 15
    calls = []

    def fail():
        calls.append(1)
        raise RuntimeError("private database connection string")

    cache.snapshot(cache, fail)
    finish(cache, Event())
    for _ in range(30):
        result = cache.snapshot(cache, fail)
        assert result["counts"]["seed_item_pending_detail"] == 3
        assert result["metadata"]["stale"]
        assert result["metadata"]["error_type"] == "RuntimeError"
        assert "private" not in str(result)
    assert calls == [1]
    now[0] += 15
    cache.snapshot(cache, lambda: {"seed_item_pending_detail": 8})
    finish(cache, Event())
    assert not cache.snapshot(cache, fail)["metadata"]["stale"]


@pytest.mark.parametrize("invalidate", ["owner", "clock"])
def test_late_result_cannot_cross_owner_or_clock_reset_and_loader_count_is_bounded(
    invalidate,
):
    now = [100.0]
    cache = StatisticsCache(clock=lambda: now[0], background_refresh=True)
    entered, release = Event(), Event()
    first, second = object(), object()
    calls = []

    def slow():
        calls.append("old")
        entered.set()
        assert release.wait(timeout=2)
        return {"seed_item_pending_detail": 99}

    try:
        cache.snapshot(first, slow)
        assert entered.wait(timeout=1)
        if invalidate == "clock":
            now[0] = 0
            second = first
        for _ in range(20):
            result = cache.snapshot(second, lambda: calls.append("new") or {})
            assert result["counts"] == {}
            assert not result["metadata"]["valid"]
        assert calls == ["old"]
    finally:
        finish(cache, release)
    assert cache.values is None
    cache.snapshot(second, lambda: {"seed_item_pending_detail": 1})
    finish(cache, release)
    assert cache.snapshot(second, slow)["counts"] == {"seed_item_pending_detail": 1}


def test_thread_creation_failure_is_throttled_without_synchronous_fallback(monkeypatch):
    cache = StatisticsCache(background_refresh=True)
    calls = []

    def fail(**_kwargs):
        calls.append(1)
        raise RuntimeError("private thread detail")

    monkeypatch.setattr(owner, "Thread", fail)
    for _ in range(10):
        result = cache.snapshot(
            cache, lambda: pytest.fail("must not run on request thread")
        )
        assert not result["metadata"]["valid"]
        assert not result["metadata"]["refreshing"]
        assert result["metadata"]["error_type"] == "RuntimeError"
    assert calls == [1]


def test_only_api_global_cache_uses_background_refresh_by_default():
    assert owner.SNAPSHOTS.background_refresh is True
    assert StatisticsCache().background_refresh is False


def test_slow_failed_refresh_retries_one_ttl_after_completion_not_start():
    now = [15.0]
    cache = StatisticsCache(clock=lambda: now[0], background_refresh=True)
    entered, release = Event(), Event()
    calls = []

    def fail():
        calls.append(1)
        entered.set()
        assert release.wait(timeout=2)
        raise OSError("private connection detail")

    try:
        cache.snapshot(cache, fail)
        assert entered.wait(timeout=1)
        now[0] = 100
    finally:
        finish(cache, release)
    now[0] = 114.9
    assert cache.snapshot(cache, fail)["metadata"]["error_type"] == "OSError"
    assert calls == [1]
    now[0] = 115
    cache.snapshot(cache, lambda: {})
    finish(cache, release)
    assert cache.snapshot(cache, fail)["metadata"]["valid"] is True


def test_status_reads_current_pause_while_statistics_query_is_blocked(monkeypatch):
    from src import server

    cache = StatisticsCache()
    cache.background_refresh = True
    entered, release = Event(), Event()
    state = {"paused": False}

    def load():
        entered.set()
        assert release.wait(timeout=2)
        return {"seed_item_raw_detail_captured": 4}

    monkeypatch.setattr(server._collection_statistics, "SNAPSHOTS", cache)
    monkeypatch.setattr(server, "DB_REPOSITORY", SimpleNamespace(enabled=True))
    monkeypatch.setattr(server, "_load_collection_seed_queue_counts", load)
    monkeypatch.setattr(
        server,
        "_collection_runtime_snapshot",
        lambda: {
            "paused": state["paused"],
            "captcha_solver": {},
            "auth_recovery": {},
            "collection_scopes": {},
        },
    )
    monkeypatch.setattr(
        server, "llm_helper", SimpleNamespace(get_api_metrics=lambda: {})
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(server._collection_api_lightweight_status_payload)
        try:
            assert entered.wait(timeout=1)
            assert pending.result(timeout=0.5)["paused"] is False
            state["paused"] = True
            current = server._collection_api_lightweight_status_payload()
            assert current["paused"] is True
            assert current["statistics"]["valid"] is False
            assert current["runtime_state"] == "统计不可用"
        finally:
            finish(cache, release)
