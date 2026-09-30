"""Bounded recovery of stalled workers; never restart their shared browser.

Run under the host controller's operation lock. An unhealthy container alone is
insufficient: matching progress must remain stale across two observations.
"""

import json
import logging
import subprocess
import time
from pathlib import Path

from .pc2_collection_watchdog import CollectionWatchdog
from .pc2_container_inventory import BROWSER, PROJECT, canonical_containers
from .pc2_settings_runtime import run
from .pc2_worker_heartbeat import finite_number, read_heartbeat, stale_heartbeat


class WorkerWatchdog(CollectionWatchdog):
    def __init__(
        self,
        root,
        *,
        runner=run,
        clock=time.time,
        probe=None,
        grace=120,
        cooldown=600,
        max_attempts=3,
        interval=30,
    ):
        super().__init__(
            root,
            runner=runner,
            clock=clock,
            grace=grace,
            cooldown=cooldown,
            max_attempts=max_attempts,
        )
        self.root = Path(root)
        self.probe = probe or (lambda cid: read_heartbeat(cid, runner=runner))
        self.interval, self.next_poll = interval, 0
        self.observations = {}

    def _read_state(self):
        state = super()._read_state()
        times = state.get("restart_times", [])
        if not isinstance(times, list) or not all(finite_number(t) for t in times):
            raise ValueError("Invalid worker restart history")
        if times != sorted(times):
            raise ValueError("Unordered worker restart history")
        return state

    @staticmethod
    def _unhealthy(row):
        state = row.get("State", {})
        return (
            state.get("Running") is True
            and state.get("Health", {}).get("Status") == "unhealthy"
        )

    def step(self):
        now = self.clock()
        if now < self.next_poll and self.next_poll - now <= self.interval:
            return "poll_wait"
        self.next_poll = now + self.interval
        ids = self.run(
            ["ps", "-aq", "--filter", "label=com.docker.compose.project=" + PROJECT]
        ).split()
        rows = (
            canonical_containers(json.loads(self.run(["inspect", *ids]))) if ids else {}
        )
        result = "healthy_or_stopped"
        for name, row in sorted(rows.items()):
            if name == BROWSER:
                continue
            if not self._unhealthy(row):
                self.observations.pop(name, None)
                continue
            self.path = self.root / f"worker-watchdog-{name}.json"
            result = self._consider(name, row, now)
            if result in {"restart_requested", "reconciliation_required"}:
                return result
        return result

    def _consider(self, name, row, now):
        try:
            previous = self._read_state()
        except (OSError, ValueError, OverflowError):
            logging.getLogger(__name__).error(
                "Worker watchdog state unavailable: %s", name
            )
            return "state_unavailable"
        if previous.get("container_id") != row["Id"]:
            previous = {}
        if previous.get("result") in {"interrupted", "restart_failed"}:
            return "reconciliation_required"
        try:
            heartbeat = stale_heartbeat(self.probe(row["Id"]), name)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            self.observations.pop(name, None)
            return "observation_unavailable"
        if heartbeat is None:
            self.observations.pop(name, None)
            return "heartbeat_not_stale"
        identity = (row["Id"], row["State"].get("StartedAt"), heartbeat)
        observed = self.observations.get(name)
        if observed is None or observed[0] != identity or now < observed[1]:
            observed = (identity, now)
            self.observations[name] = observed
        if now - observed[1] < self.grace:
            return "watching"
        # Rolling daily cap survives process restarts and transient healthy states.
        times = [t for t in previous.get("restart_times", []) if now - t < 86400]
        if len(times) >= self.max_attempts:
            self.persist(
                {
                    **previous,
                    "result": "restart_limit_reached",
                    "alert": "manual_intervention_required",
                }
            )
            return "restart_limit_reached"
        if times and now - times[-1] < self.cooldown * 2 ** (len(times) - 1):
            return "cooldown"
        return self._restart(name, row, heartbeat, now, times)

    def _restart(self, name, row, heartbeat, now, times):
        fresh = canonical_containers(json.loads(self.run(["inspect", row["Id"]]))).get(
            name
        )
        if (
            not fresh
            or fresh["Id"] != row["Id"]
            or not self._unhealthy(fresh)
            or fresh["State"].get("StartedAt") != row["State"].get("StartedAt")
        ):
            self.observations.pop(name, None)
            return "state_changed"
        try:
            latest = stale_heartbeat(self.probe(row["Id"]), name)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            latest = None
        if latest != heartbeat:
            self.observations.pop(name, None)
            return "state_changed"
        receipt = {
            "service": name,
            "container_id": row["Id"],
            "started_at": row["State"].get("StartedAt"),
            "heartbeat": heartbeat,
            "attempted_at": now,
            "restart_times": [*times, now],
            "consecutive_attempts": len(times) + 1,
            "result": "interrupted",
        }
        self.persist(receipt)
        try:
            self.run(["restart", "--time", "30", row["Id"]], timeout=60)
        except Exception:
            self.persist(
                {
                    **receipt,
                    "result": "restart_failed",
                    "alert": "restart_command_failed",
                }
            )
            raise
        self.persist({**receipt, "result": "restart_requested"})
        self.observations.pop(name, None)
        print(
            json.dumps(
                {
                    "event": "worker_watchdog_restart",
                    "service": name,
                    "container_id": row["Id"],
                    "attempt": len(times) + 1,
                }
            ),
            flush=True,
        )
        return "restart_requested"
