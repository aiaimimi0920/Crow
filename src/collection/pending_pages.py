"""Walk bounded database pages rather than repeatedly inspecting only the head."""

from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from typing import Any


def pending_pages(
    query: Callable[..., list[dict[str, Any]]], limit: int
) -> Iterator[dict[str, Any]]:
    offset = 0
    while True:
        page = query(limit=limit, offset=offset) if offset else query(limit=limit)
        yield from page
        if len(page) < limit:
            return
        offset += len(page)


def expire_dispatches(
    dispatched_tasks: dict[str, datetime], now: datetime, cooldown_seconds: int
) -> None:
    """Expire transient cooldowns without modifying persisted task state."""
    expired = [
        item_id
        for item_id, dispatched_at in dispatched_tasks.items()
        if (
            now
            - (
                dispatched_at.replace(tzinfo=timezone.utc)
                if dispatched_at.tzinfo is None
                else dispatched_at
            )
        ).total_seconds()
        >= cooldown_seconds
    ]
    for item_id in expired:
        dispatched_tasks.pop(item_id, None)
