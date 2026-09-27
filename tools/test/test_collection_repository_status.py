"""Repository status read boundaries preserve fallback and failure behavior."""

from types import SimpleNamespace

import pytest


@pytest.fixture(params=["facade", "native"])
def api(monkeypatch, request):
    from src import collection_repository_status, server

    def bind(repository):
        if request.param == "native":
            return SimpleNamespace(
                pending=lambda limit=100: (
                    collection_repository_status.pending_candidates(
                        repository, prefer_db_reads=repository.enabled, limit=limit
                    )
                ),
                counts=lambda: collection_repository_status.counts_snapshot(repository),
                supply=lambda hours=24: (
                    collection_repository_status.data_supply_snapshot(
                        repository, hours=hours
                    )
                ),
            )
        monkeypatch.setattr(server, "DB_REPOSITORY", repository)
        monkeypatch.setattr(server, "_prefer_db_task_reads", lambda: repository.enabled)
        return SimpleNamespace(
            pending=server._db_pending_task_candidates,
            counts=server._db_counts_snapshot,
            supply=server._db_data_supply_snapshot,
        )

    return bind


def test_disabled_repository_needs_no_query_methods(api):
    reads = api(SimpleNamespace(enabled=False))
    assert reads.pending(7) == []
    assert reads.counts() == {
        "db_total_ids": 0,
        "db_processed_ids": 0,
        "db_pending_ids": 0,
        "db_detail_captured_ids": 0,
    }
    assert reads.supply() == {
        "detail_archive_fetch_recent": {},
        "maintenance_writeback_recent": {},
        "stage_transition_recent": {},
    }


def test_pending_query_preserves_limit_and_logs_failure(api, caplog):
    result = [{"id": "item", "url": "https://example.com", "status": "pending"}]
    limits = []

    def pending(*, limit):
        limits.append(limit)
        if limit == 9:
            raise RuntimeError("query unavailable")
        return result

    reads = api(SimpleNamespace(enabled=True, iter_pending_task_items=pending))
    assert reads.pending(7) is result
    assert reads.pending(9) == []
    assert limits == [7, 9]
    record = next(
        r for r in caplog.records if r.message == "[DB] Pending task query failed"
    )
    assert record.exc_info[0] is RuntimeError


def test_counts_fallback_and_its_failure_propagation(api):
    calls = []

    def failed():
        raise RuntimeError("read unavailable")

    def count(name, value):
        calls.append(name)
        return value

    repository = SimpleNamespace(
        enabled=True,
        counts_snapshot=failed,
        count_listings=lambda: count("total", 10),
        count_processed_listings=lambda: count("processed", 4),
        count_pending_task_items=lambda: count("pending", 6),
        count_detail_captured_items=lambda: count("captured", 5),
    )
    reads = api(repository)
    assert reads.counts() == {
        "db_total_ids": 10,
        "db_processed_ids": 4,
        "db_pending_ids": 6,
        "db_detail_captured_ids": 5,
    }
    assert calls == ["total", "processed", "pending", "captured"]
    repository.count_listings = failed
    with pytest.raises(RuntimeError, match="read unavailable"):
        reads.counts()
    expected = {"db_total_ids": 20}
    repository.counts_snapshot = lambda: expected
    assert reads.counts() is expected


def test_event_groups_keep_hours_and_propagate_failure(api):
    calls = []

    def events(types, *, hours):
        calls.append((types, hours))
        if hours == 3:
            raise ValueError("event read failed")
        return {types[0]: 2}

    reads = api(SimpleNamespace(enabled=True, event_type_counts=events))
    result = reads.supply(12)
    assert len(calls) == 3
    assert all(hours == 12 for _, hours in calls)
    assert result["detail_archive_fetch_recent"] == {"detail_archive_fetched": 2}
    assert result["maintenance_writeback_recent"] == {"detail_replay_prepared": 2}
    assert result["stage_transition_recent"] == {"seed_stage_transition": 2}
    with pytest.raises(ValueError, match="event read failed"):
        reads.supply(3)
    assert len(calls) == 4
    reads = api(SimpleNamespace(enabled=True))
    assert all(not counts for counts in reads.supply().values())
