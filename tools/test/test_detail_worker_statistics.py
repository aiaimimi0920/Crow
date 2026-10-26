"""Worker progress must not rescan every row for each result and summary."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from src.collection_statistics import StatisticsCache
from tools import detail_worker_statistics as owner
from tools.test.seed_queue_repository_test_context import (
    _ensure_nansha_job,
    _make_repo,
    _upsert_sample_seed,
)


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(
        owner,
        "_STATISTICS",
        StatisticsCache(ttl=15.0, clock=lambda: now[0], wall_clock=lambda: now[0]),
    )
    return now


def test_repeated_worker_snapshots_issue_four_queries_once_per_ttl(tmp_path, clock):
    repo = _make_repo(tmp_path)
    _ensure_nansha_job(repo)
    _upsert_sample_seed(repo, "first")
    statements = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(repo.engine, "before_cursor_execute", record)
    try:
        for _ in range(30):
            result = owner.worker_queue_statistics(repo)
            assert result["counts"]["seed_item_pending_detail"] == 1
        assert len(statements) == 4
        assert result["counts_metadata"]["valid"]
        assert result["counts_metadata"]["ttl_seconds"] == 15
        # Raw repository reads stay fresh, and claims are not served from this cache.
        _upsert_sample_seed(repo, "second")
        assert repo.seed_queue_counts()["seed_item_pending_detail"] == 2
        assert repo.claim_seed_detail_item("fixture-worker", lease_seconds=30)
        assert repo.seed_queue_counts()["seed_item_in_progress"] == 1
        statements.clear()
        assert (
            owner.worker_queue_statistics(repo)["counts"]["seed_item_in_progress"] == 0
        )
        assert statements == []
        clock[0] += 15
        result = owner.worker_queue_statistics(repo)
        assert result["counts"]["seed_item_in_progress"] == 1
        assert len(statements) == 4
    finally:
        event.remove(repo.engine, "before_cursor_execute", record)


def test_snapshots_single_flight_and_return_independent_copies(clock):
    calls = []
    repo = SimpleNamespace(
        seed_queue_counts=lambda: calls.append(1) or {"seed_occurrence_total": 10}
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(lambda _: owner.worker_queue_statistics(repo), range(20))
        )
    assert calls == [1]
    results[0]["counts"]["seed_occurrence_total"] = -1
    assert results[1]["counts"]["seed_occurrence_total"] == 10
    clock[0] += 5
    assert owner.worker_queue_statistics(repo)["counts_metadata"]["age_seconds"] == 5


def test_failed_refresh_is_marked_stale_and_not_retried_for_every_item(clock):
    calls = []

    def load():
        calls.append(1)
        if len(calls) > 1:
            raise OSError("private database connection detail")
        return {"seed_occurrence_total": 10}

    repo = SimpleNamespace(seed_queue_counts=load)
    owner.worker_queue_statistics(repo)
    clock[0] += 15
    for _ in range(30):
        result = owner.worker_queue_statistics(repo)
        assert result["counts"] == {"seed_occurrence_total": 10}
        assert result["counts_metadata"]["stale"] is True
        assert result["counts_metadata"]["error_type"] == "OSError"
    assert len(calls) == 2
    assert "private" not in str(result)
    other = SimpleNamespace(seed_queue_counts=lambda: {"seed_occurrence_total": 99})
    assert owner.worker_queue_statistics(other)["counts"] == {
        "seed_occurrence_total": 99
    }
