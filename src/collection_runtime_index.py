"""Shared in-process collection index and pending task queue."""

from __future__ import annotations

from _thread import RLock
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class CollectionRuntimeIndex:
    """Own collection records, pending IDs and dispatch cooldowns under one lock."""

    lock: RLock = field(default_factory=RLock, repr=False)
    seen_ids: dict[str, dict[str, object]] = field(default_factory=dict)
    pending_tasks: list[str] = field(default_factory=list)
    dispatched_tasks: dict[str, Any] = field(default_factory=dict)

    def clear(self) -> None:
        with self.lock:
            self.seen_ids.clear()
            self.pending_tasks.clear()
            self.dispatched_tasks.clear()

    def queue_pending(self, item_id: str) -> bool:
        with self.lock:
            if item_id in self.pending_tasks:
                return False
            self.pending_tasks.append(item_id)
            return True

    def set_seen(self, item_id: str, entry: dict[str, object]) -> None:
        with self.lock:
            self.seen_ids[item_id] = entry

    def get_seen(self, item_id: str) -> dict[str, object] | None:
        with self.lock:
            return self.seen_ids.get(item_id)

    def remove_seen(self, item_id: str) -> None:
        with self.lock:
            self.seen_ids.pop(item_id, None)

    def remove_pending(self, item_id: str) -> None:
        with self.lock:
            try:
                self.pending_tasks.remove(item_id)
            except ValueError:
                pass

    def prune_processed_pending(self) -> int:
        with self.lock:
            before = len(self.pending_tasks)
            self.pending_tasks[:] = [
                item_id
                for item_id in self.pending_tasks
                if not self.seen_ids.get(item_id, {})
                .get("data", {})
                .get("is_processed")
            ]
            return before - len(self.pending_tasks)

    def prune_unavailable_pending(self) -> int:
        with self.lock:
            before = len(self.pending_tasks)
            self.pending_tasks[:] = [
                item_id
                for item_id in self.pending_tasks
                if item_id in self.seen_ids
                and not self.seen_ids[item_id].get("data", {}).get("is_processed")
            ]
            return before - len(self.pending_tasks)

    def mark_dispatched(self, item_id: str, timestamp: Any) -> None:
        with self.lock:
            self.dispatched_tasks[item_id] = timestamp

    def get_dispatched(self, item_id: str) -> Any:
        with self.lock:
            return self.dispatched_tasks.get(item_id)

    def prune_dispatched(self, now: datetime, cooldown_seconds: int) -> None:
        with self.lock:
            expired = []
            for item_id, dispatched_at in self.dispatched_tasks.items():
                if dispatched_at.tzinfo is None:
                    dispatched_at = dispatched_at.replace(tzinfo=now.tzinfo)
                if (now - dispatched_at).total_seconds() >= cooldown_seconds:
                    expired.append(item_id)
            for item_id in expired:
                self.dispatched_tasks.pop(item_id, None)

    def snapshot(self) -> tuple[dict[str, dict[str, object]], tuple[str, ...]]:
        with self.lock:
            return dict(self.seen_ids), tuple(self.pending_tasks)

    def state_snapshot(
        self,
    ) -> tuple[dict[str, dict[str, object]], tuple[str, ...], dict[str, Any]]:
        """Return consistent copies for status and read-only dispatch decisions."""
        with self.lock:
            return (
                dict(self.seen_ids),
                tuple(self.pending_tasks),
                dict(self.dispatched_tasks),
            )

    def counts_snapshot(self) -> tuple[int, int]:
        with self.lock:
            return len(self.seen_ids), len(self.pending_tasks)

    def claim_next_pending(
        self, now: datetime, cooldown_seconds: int
    ) -> dict[str, object] | None:
        """Atomically choose and mark one legacy detail task."""
        with self.lock:
            self.pending_tasks[:] = [
                item_id
                for item_id in self.pending_tasks
                if item_id in self.seen_ids
                and not self.seen_ids[item_id].get("data", {}).get("is_processed")
            ]
            for item_id in self.pending_tasks:
                dispatched_at = self.dispatched_tasks.get(item_id)
                if dispatched_at is not None:
                    if dispatched_at.tzinfo is None:
                        dispatched_at = dispatched_at.replace(tzinfo=now.tzinfo)
                    if (now - dispatched_at).total_seconds() < cooldown_seconds:
                        continue
                self.dispatched_tasks[item_id] = now
                return dict(self.seen_ids[item_id].get("data", {}))
        return None

    def claim_pending_batch(
        self, now: datetime, cooldown_seconds: int, batch_size: int
    ) -> tuple[list[dict[str, object]], int, int, int]:
        """Atomically select legacy detail tasks and mark their dispatch times."""
        with self.lock:
            self.pending_tasks[:] = [
                item_id
                for item_id in self.pending_tasks
                if item_id in self.seen_ids
                and not self.seen_ids[item_id].get("data", {}).get("is_processed")
            ]
            total_count = len(self.seen_ids)
            pending_count = len(self.pending_tasks)
            tasks: list[dict[str, object]] = []
            for item_id in self.pending_tasks:
                dispatched_at = self.dispatched_tasks.get(item_id)
                if dispatched_at is not None:
                    if dispatched_at.tzinfo is None:
                        dispatched_at = dispatched_at.replace(tzinfo=now.tzinfo)
                    if (now - dispatched_at).total_seconds() < cooldown_seconds:
                        continue
                item = self.seen_ids[item_id].get("data")
                if not isinstance(item, dict):
                    continue
                tasks.append({"id": item_id, "url": item.get("url")})
                self.dispatched_tasks[item_id] = now
                if len(tasks) >= batch_size:
                    break
            return tasks, total_count, total_count - pending_count, pending_count
