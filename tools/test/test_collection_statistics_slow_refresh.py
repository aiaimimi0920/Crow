"""A slow synchronous telemetry read must still leave a full refresh cooldown."""

from types import SimpleNamespace

import pytest

from src.collection_statistics import StatisticsCache
from tools import detail_worker_statistics


@pytest.mark.parametrize("fail_refresh", [False, True])
def test_slow_worker_refresh_waits_a_full_ttl_after_completion(
    monkeypatch, fail_refresh
):
    now = [0.0]
    cache = StatisticsCache(clock=lambda: now[0], wall_clock=lambda: now[0])
    monkeypatch.setattr(detail_worker_statistics, "_STATISTICS", cache)
    calls = []

    def load():
        calls.append(now[0])
        if len(calls) == 2:
            now[0] += 40
            if fail_refresh:
                raise OSError("PRIVATE_DATABASE_DETAIL")
        return {"seed_item_pending_detail": len(calls)}

    repository = SimpleNamespace(seed_queue_counts=load)
    detail_worker_statistics.worker_queue_statistics(repository)
    now[0] = 15
    result = detail_worker_statistics.worker_queue_statistics(repository)
    assert calls == [0, 15]
    assert now[0] == 55
    assert result["counts"] == {"seed_item_pending_detail": 1 if fail_refresh else 2}
    metadata = result["counts_metadata"]
    assert metadata["generated_at"] == (0 if fail_refresh else 55)
    assert metadata["age_seconds"] == (55 if fail_refresh else 0)
    assert metadata["stale"] is fail_refresh
    assert metadata["error_type"] == ("OSError" if fail_refresh else None)
    assert "PRIVATE_DATABASE_DETAIL" not in str(result)

    for instant in (55, 60, 69.999):
        now[0] = instant
        assert detail_worker_statistics.worker_queue_statistics(repository) == {
            "counts": result["counts"],
            "counts_metadata": {
                **metadata,
                "age_seconds": instant if fail_refresh else instant - 55,
            },
        }
    assert calls == [0, 15]
    now[0] = 70
    refreshed = detail_worker_statistics.worker_queue_statistics(repository)
    assert calls == [0, 15, 70]
    assert refreshed["counts"] == {"seed_item_pending_detail": 3}
    assert not refreshed["counts_metadata"]["stale"]


def test_slow_refresh_does_not_delay_new_owner_or_clock_reset():
    now = [100.0]
    cache = StatisticsCache(clock=lambda: now[0])

    def slow():
        now[0] += 40
        return {"seed_item_pending_detail": 1}

    first, second = object(), object()
    cache.snapshot(first, slow)
    assert cache.snapshot(second, lambda: {"seed_item_pending_detail": 2})[
        "counts"
    ] == {"seed_item_pending_detail": 2}
    now[0] = 0
    assert cache.snapshot(second, lambda: {"seed_item_pending_detail": 3})[
        "counts"
    ] == {"seed_item_pending_detail": 3}
