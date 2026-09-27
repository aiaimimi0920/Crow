"""Seed queue count defaults and legacy repository fallback."""

from collections.abc import Callable, Mapping
from typing import Protocol, cast


class QueueRepository(Protocol):
    @property
    def enabled(self) -> bool: ...


class _SeedCountsRepository(Protocol):
    def seed_queue_counts(self) -> Mapping[str, int]: ...


class _SearchCountsRepository(Protocol):
    def search_task_counts(self) -> Mapping[str, str | int | None]: ...


def empty_counts() -> dict[str, int]:
    return {
        "seed_scan_job_pending": 0,
        "seed_scan_job_in_progress": 0,
        "seed_scan_job_completed": 0,
        "seed_scan_job_blocked": 0,
        "seed_scan_progress_pending": 0,
        "seed_scan_progress_in_progress": 0,
        "seed_scan_progress_exhausted": 0,
        "seed_scan_progress_blocked": 0,
        "seed_item_pending_detail": 0,
        "seed_item_in_progress": 0,
        "seed_item_raw_detail_captured": 0,
        "seed_item_analysis_in_progress": 0,
        "seed_item_analysis_failed": 0,
        "seed_item_analysis_blocked": 0,
        "seed_item_detail_completed": 0,
        "seed_item_detail_failed": 0,
        "seed_item_detail_blocked": 0,
        "seed_occurrence_total": 0,
    }


def load_counts(
    repository: QueueRepository,
    *,
    defaults: Callable[[], dict[str, int]] = empty_counts,
) -> dict[str, int]:
    counts = defaults()
    if repository.enabled and hasattr(repository, "seed_queue_counts"):
        counts.update(cast(_SeedCountsRepository, repository).seed_queue_counts())
    elif repository.enabled and hasattr(repository, "search_task_counts"):
        search = cast(_SearchCountsRepository, repository).search_task_counts()
        counts["seed_scan_job_pending"] = int(search.get("search_pending", 0) or 0)
        counts["seed_scan_job_in_progress"] = int(
            search.get("search_in_progress", 0) or 0
        )
        counts["seed_scan_job_completed"] = int(search.get("search_done", 0) or 0)
        counts["seed_scan_job_blocked"] = int(search.get("search_pruned", 0) or 0)
    return counts
