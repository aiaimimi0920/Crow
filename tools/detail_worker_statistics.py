"""Bounded worker telemetry snapshots; never cache claims, leases or control state."""

from src.collection_statistics import StatisticsCache

_STATISTICS = StatisticsCache(ttl=15.0)


def worker_queue_statistics(repository):
    snapshot = _STATISTICS.snapshot(repository, repository.seed_queue_counts)
    return {"counts": snapshot["counts"], "counts_metadata": snapshot["metadata"]}
