"""Repository-backed authentication recovery progress signals."""

from typing import Protocol


class ProgressRepository(Protocol):
    enabled: bool

    def seed_queue_counts(self) -> object: ...


def captured_detail_count(repository: ProgressRepository) -> int | None:
    if not getattr(repository, "enabled", False):
        return None
    try:
        counts = repository.seed_queue_counts()
    except Exception:
        return None
    if not isinstance(counts, dict):
        return None
    captured_status_keys = (
        "seed_item_raw_detail_captured",
        # Analysis states are included because each can only be entered after
        # raw detail HTML was captured successfully. Moving between these
        # states therefore keeps the total stable instead of inventing progress.
        "seed_item_analysis_in_progress",
        "seed_item_analysis_failed",
        "seed_item_analysis_blocked",
        "seed_item_detail_completed",
    )
    try:
        return sum(max(int(counts.get(key, 0) or 0), 0) for key in captured_status_keys)
    except (TypeError, ValueError):
        return None


def pending_detail_count(repository: ProgressRepository) -> int:
    if not getattr(repository, "enabled", False):
        return 0
    try:
        counts = repository.seed_queue_counts()
    except Exception:
        return 0
    if not isinstance(counts, dict):
        return 0
    try:
        return max(int(counts.get("seed_item_pending_detail", 0) or 0), 0) + max(
            int(counts.get("seed_item_in_progress", 0) or 0),
            0,
        )
    except (TypeError, ValueError):
        return 0
