"""Bounded telemetry snapshots; runtime control state is never cached."""

from collections import deque
from threading import RLock, Thread
import time


def unique_counts(counts: dict[str, int]) -> list[int]:
    finalized = counts.get("seed_item_detail_completed", 0)
    captured = finalized + sum(
        counts.get("seed_item_" + status, 0)
        for status in (
            "raw_detail_captured",
            "analysis_in_progress",
            "analysis_failed",
            "analysis_blocked",
        )
    )
    return [
        sum(value for key, value in counts.items() if key.startswith("seed_item_")),
        captured,
        finalized,
    ]


class StatisticsCache:
    def __init__(
        self,
        *,
        ttl=15.0,
        clock=time.monotonic,
        wall_clock=time.time,
        background_refresh=False,
    ):
        self.ttl, self.clock, self.wall_clock = ttl, clock, wall_clock
        self.background_refresh = background_refresh
        self.lock = RLock()
        self.owner = None
        self.values = None
        self.attempted = float("-inf")
        self.sampled = 0.0
        self.generated_at = None
        self.error = None
        self.history = deque(maxlen=32)
        self._generation = 0
        self._refresh_generation = None
        self._refresh_thread = None

    def snapshot(self, owner, load):
        with self.lock:
            now = self.clock()
            if self.owner is not owner or now < self.attempted:
                self.owner, self.values = owner, None
                self.attempted = float("-inf")
                self.generated_at = self.error = None
                self.history.clear()
                self._generation += 1
            if now - self.attempted >= self.ttl and self._refresh_thread is None:
                self.attempted = now
                if self.background_refresh:
                    self._refresh_generation = self._generation
                    try:
                        self._refresh_thread = Thread(
                            target=self._refresh,
                            args=(owner, self._generation, load),
                            name="collection-statistics-refresh",
                            daemon=True,
                        )
                        self._refresh_thread.start()
                    except Exception as error:
                        self._refresh_thread = None
                        self.error = type(error).__name__
                else:
                    self._refresh(owner, self._generation, load)
            return self._snapshot()

    def _refresh(self, owner, generation, load):
        # Background I/O must never hold the snapshot/control request lock.
        try:
            values = dict(load())
            if any(not isinstance(v, int) or v < 0 for v in values.values()):
                raise ValueError("Invalid collection counts")
            sample = unique_counts(values)
            error = None
        except Exception as exc:
            values, sample, error = None, None, type(exc).__name__
        with self.lock:
            if self.owner is owner and self._generation == generation:
                self.error = error
                if self.background_refresh:
                    self.attempted = self.clock()
                if values is not None:
                    self.values = values
                    self.sampled = self.clock()
                    self.generated_at = self.wall_clock()
                    while self.history and self.history[0][0] < self.sampled - 90:
                        self.history.popleft()
                    self.history.append((self.sampled, sample))
            # At most one loader, even across owner changes; old results are discarded.
            self._refresh_thread = None

    def _snapshot(self):
        age = max(0.0, self.clock() - self.sampled) if self.values is not None else None
        stale = self.error is not None or (age is not None and age >= self.ttl)
        baseline = next(
            (
                sample
                for sample in reversed(self.history)
                if 60 <= self.sampled - sample[0] <= 90
            ),
            None,
        )
        delta = [None, None, None]
        if baseline and self.values is not None and not stale:
            delta = [
                current - old
                for current, old in zip(unique_counts(self.values), baseline[1])
            ]
        return {
            "counts": dict(self.values or {}),
            "metadata": {
                "valid": self.values is not None,
                "stale": stale,
                "refreshing": self._refresh_thread is not None
                and self._refresh_generation == self._generation,
                "error_type": self.error,
                "generated_at": self.generated_at,
                "age_seconds": age,
                "ttl_seconds": self.ttl,
                "minute_delta": delta,
                "window_seconds": round(self.sampled - baseline[0])
                if baseline and not stale
                else None,
            },
        }


# API telemetry is stale-while-revalidate. Worker caches remain synchronous by default.
SNAPSHOTS = StatisticsCache(background_refresh=True)
