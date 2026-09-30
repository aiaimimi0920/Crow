"""Recover a healthy-but-stalled browser only with continuous collection evidence."""

import json
import logging
import math
import subprocess
import time
from pathlib import Path

from .pc2_browser_session import BrowserSession
from .pc2_collection_progress import progress_sample, read_progress
from .pc2_collection_watchdog import CollectionWatchdog
from .pc2_container_inventory import BROWSER, PROJECT, canonical_containers
from .pc2_settings_runtime import run


class CollectionProgressWatchdog(CollectionWatchdog):
    def __init__(
        self,
        root,
        *,
        runner=run,
        clock=time.time,
        probe=None,
        session=None,
        stall=900,
        interval=60,
        max_attempts=2,
    ):
        super().__init__(root, runner=runner, clock=clock, max_attempts=max_attempts)
        self.path = Path(root) / "progress-watchdog.json"
        self.stall, self.interval = stall, interval
        self.probe = probe or (lambda cid: read_progress(cid, runner=runner))
        self.session = session or BrowserSession(runner=runner)
        self.next_poll = 0

    def inventory(self):
        ids = self.run(
            ["ps", "-aq", "--filter", "label=com.docker.compose.project=" + PROJECT]
        ).split()
        return (
            canonical_containers(json.loads(self.run(["inspect", *ids]))) if ids else {}
        )

    def _read_state(self):
        state = super()._read_state()
        for key in ("observed_at", "progress_at"):
            value = state.get(key, 0)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Invalid progress observation time")
        counts = state.get("counters", [])
        if (
            not isinstance(counts, list)
            or len(counts) not in (0, 4)
            or any(type(v) is not int or v < 0 for v in counts)
        ):
            raise ValueError("Invalid saved progress counts")
        return state

    def step(self):
        now = self.clock()
        if now < self.next_poll and self.next_poll - now <= self.interval:
            return "poll_wait"
        self.next_poll = now + self.interval
        try:
            previous = self._read_state()
        except (OSError, ValueError, OverflowError):
            logging.getLogger(__name__).error(
                "Progress watchdog state unavailable; restart suspended"
            )
            return "state_unavailable"
        if previous.get("result") in {
            "interrupted",
            "restart_failed",
            "session_restore_failed",
        }:
            return "reconciliation_required"
        rows = self.inventory()
        row = rows.get(BROWSER)
        state = row.get("State", {}) if row else {}
        active = any(
            name.startswith(("pc2-seed-", "pc2-detail-"))
            and r.get("State", {}).get("Running")
            for name, r in rows.items()
        )
        if (
            not active
            or not state.get("Running")
            or state.get("Health", {}).get("Status") != "healthy"
        ):
            self.persist(
                {
                    **previous,
                    "observed_at": now,
                    "progress_at": now,
                    "result": "browser_or_workers_not_ready",
                }
            )
            return "browser_or_workers_not_ready"
        try:
            sample = progress_sample(self.probe(row["Id"]))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            self.persist(
                {
                    **previous,
                    "observed_at": now,
                    "progress_at": now,
                    "result": "observation_unavailable",
                }
            )
            return "observation_unavailable"
        counters = sample["counters"]
        old = previous.get("counters", [])
        changed = counters != old
        advanced = (
            len(old) == 4
            and all(a >= b for a, b in zip(counters, old, strict=True))
            and changed
        )
        interrupted = (
            previous.get("container_id") != row["Id"]
            or previous.get("started_at") != state.get("StartedAt")
            or now < previous.get("observed_at", now)
            or now - previous.get("observed_at", 0) > self.interval * 3
        )
        receipt = {
            **previous,
            "container_id": row["Id"],
            "started_at": state.get("StartedAt"),
            "observed_at": now,
            "counters": counters,
            "consecutive_attempts": 0
            if advanced
            else previous.get("consecutive_attempts", 0),
        }
        if changed or interrupted or not sample["eligible"]:
            receipt.update(
                progress_at=now, result="progress" if advanced else sample["reason"]
            )
            self.persist(receipt)
            return receipt["result"]
        if receipt["consecutive_attempts"] >= self.max_attempts:
            self.persist(
                {
                    **receipt,
                    "result": "restart_limit_reached",
                    "alert": "manual_intervention_required",
                }
            )
            return "restart_limit_reached"
        cooldown = self.stall * 2 ** receipt["consecutive_attempts"]
        if (
            now - receipt.get("progress_at", now) < self.stall
            or now - receipt.get("attempted_at", 0) < cooldown
        ):
            self.persist({**receipt, "result": "watching"})
            return "watching"
        # A checkpoint and a second fresh read precede any disruptive action.
        checkpoint = self.session.capture(row)
        fresh = self.inventory().get(BROWSER)
        latest = progress_sample(self.probe(row["Id"]))
        current = fresh.get("State", {}) if fresh else {}
        if (
            not fresh
            or fresh["Id"] != row["Id"]
            or not current.get("Running")
            or current.get("StartedAt") != state.get("StartedAt")
            or current.get("Health", {}).get("Status") != "healthy"
            or latest != sample
        ):
            self.persist({**receipt, "progress_at": now, "result": "state_changed"})
            return "state_changed"
        receipt.update(
            attempted_at=now,
            progress_at=now,
            result="interrupted",
            consecutive_attempts=receipt["consecutive_attempts"] + 1,
            checkpoint=checkpoint,
        )
        self.persist(receipt)
        try:
            self.run(["restart", "--time", "30", row["Id"]], timeout=60)
        except Exception:
            self.persist({**receipt, "result": "restart_failed"})
            raise
        try:
            self.session.restore(row["Id"], checkpoint)
        except Exception:
            self.persist({**receipt, "result": "session_restore_failed"})
            raise
        self.persist({**receipt, "result": "restart_requested"})
        print(
            "Collection progress watchdog restarted stalled browser; session restored; progress pending",
            flush=True,
        )
        return "restart_requested"
