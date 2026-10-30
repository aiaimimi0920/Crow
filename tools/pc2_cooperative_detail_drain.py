"""Scoped detail-worker drain for a caller holding the host operation lock.

This helper has no CLI and never uses Docker stop/restart or SIGKILL. The caller
must bind the expected canonical identities and persist snapshots privately.
"""

from __future__ import annotations

import json
import math
import re
import time
from copy import deepcopy


class CooperativeDetailDrain:
    def __init__(
        self,
        docker,
        expected,
        persist,
        *,
        clock=time.monotonic,
        sleep=time.sleep,
        drain_timeout=240,
        recovery_timeout=240,
    ):
        if set(expected) != {f"fapaifang-pc2-detail-{n}" for n in range(1, 4)}:
            raise ValueError("Exactly three canonical detail workers are required")
        if any(
            not re.fullmatch(r"[a-f0-9]{64}", row.get("id", ""))
            for row in expected.values()
        ):
            raise ValueError("Invalid expected detail identity")
        if any(
            type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            for value in (drain_timeout, recovery_timeout)
        ):
            raise ValueError("Maintenance timeouts must be finite positive numbers")
        self.docker, self.expected, self.persist = docker, deepcopy(expected), persist
        self.clock, self.sleep = clock, sleep
        self.drain_timeout, self.recovery_timeout = drain_timeout, recovery_timeout
        self.before, self.touched, self.signaled = {}, set(), set()
        self.drained = False
        self.drained_states = {}

    def _row(self, name):
        row = self.docker.inspect(name)
        expected = self.expected[name]
        if (
            row["Id"] != expected["id"]
            or row["Name"] != "/" + name
            or row["Image"] != expected["image"]
        ):
            raise RuntimeError("Dependent worker identity changed")
        return row

    @staticmethod
    def _contract(row):
        host = deepcopy(row["HostConfig"])
        host.pop("RestartPolicy", None)
        # Docker serializes its mount map in unspecified order. Compare every
        # mount field, but do not treat serialization order as a storage change.
        mounts = sorted(
            row["Mounts"], key=lambda value: json.dumps(value, sort_keys=True)
        )
        return row["Config"], host, mounts

    def __enter__(self):
        if self.before:
            raise RuntimeError("Cooperative drain cannot be replayed")
        for name in sorted(self.expected):
            row = self._row(name)
            if (
                not row["State"]["Running"]
                or row["State"]["Pid"] != self.expected[name]["pid"]
            ):
                raise RuntimeError(
                    "Dependent worker is not the inspected running process"
                )
            if row["HostConfig"]["RestartPolicy"]["Name"] not in {
                "no",
                "always",
                "unless-stopped",
                "on-failure",
            }:
                raise ValueError("Unsupported dependent restart policy")
            self.before[name] = deepcopy(row)
        self.persist("dependent-workers.before.private.json", self.before)
        try:
            for name in sorted(self.before):
                row = self._row(name)
                # Runtime counters may advance, but storage/config/process must not.
                if (
                    self._contract(row) != self._contract(self.before[name])
                    or row["State"]["Pid"] != self.before[name]["State"]["Pid"]
                ):
                    raise RuntimeError("Dependent worker drift before drain")
                self.touched.add(name)
                self.docker.action(
                    row["Id"],
                    "update",
                    {"RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}},
                )
            for name in sorted(self.before):
                row = self._row(name)
                if (
                    self._contract(row) != self._contract(self.before[name])
                    or row["State"]["Pid"] != self.before[name]["State"]["Pid"]
                ):
                    raise RuntimeError("Dependent process changed before signal")
                if row["HostConfig"]["RestartPolicy"]["Name"] != "no":
                    raise RuntimeError("Dependent restart policy was not disabled")
                if row["State"]["Running"]:
                    self.signaled.add(name)
                    self.docker.action(row["Id"], "kill?signal=SIGTERM")
            deadline = self.clock() + self.drain_timeout
            while True:
                rows = {name: self._row(name) for name in self.before}
                if all(not row["State"]["Running"] for row in rows.values()):
                    if any(row["State"].get("ExitCode") != 0 for row in rows.values()):
                        raise RuntimeError("Dependent worker did not exit cleanly")
                    self.drained_states = {
                        name: self._exit_identity(row) for name, row in rows.items()
                    }
                    self.drained = True
                    self.persist(
                        "dependent-workers.drained.safe.json", self._summary(rows)
                    )
                    return self
                if self.clock() >= deadline:
                    raise TimeoutError(
                        "Cooperative drain timed out; no force stop permitted"
                    )
                self.sleep(1)
        except BaseException:
            self._recover()
            raise

    def require_drained(self):
        rows = {name: self._row(name) for name in self.before}
        if not self.drained or any(
            row["State"]["Running"]
            or row["State"].get("ExitCode") != 0
            or self._exit_identity(row) != self.drained_states.get(name)
            or row["HostConfig"]["RestartPolicy"]["Name"] != "no"
            or self._contract(row) != self._contract(self.before[name])
            for name, row in rows.items()
        ):
            raise RuntimeError("Dependent worker drain is no longer valid")

    @staticmethod
    def _exit_identity(row):
        return tuple(row["State"].get(key) for key in ("StartedAt", "FinishedAt"))

    def _summary(self, rows):
        return {
            "drained": self.drained,
            "workers": {
                name: {
                    "id": row["Id"],
                    "pid": row["State"]["Pid"],
                    "running": row["State"]["Running"],
                    "exit_code": row["State"].get("ExitCode"),
                    "health": row["State"].get("Health", {}).get("Status"),
                    "signal_attempted": name in self.signaled,
                }
                for name, row in rows.items()
            },
        }

    def _recovery_summary(self, errors):
        rows, unavailable = {}, []
        for name in self.before:
            try:
                rows[name] = self._row(name)
            except Exception:  # noqa: BLE001 - retain diagnostics for every unavailable target
                unavailable.append(name)
        return {
            **self._summary(rows),
            "unavailable": unavailable,
            "failed_targets": sorted(set(errors)),
        }

    def _recover(self):
        errors = []
        # Attempt every original policy even if another target cannot be restored.
        for name in sorted(self.touched):
            try:
                row = self._row(name)
                if self._contract(row) != self._contract(self.before[name]):
                    raise RuntimeError(
                        "Dependent configuration changed during maintenance"
                    )
                self.docker.action(
                    row["Id"],
                    "update",
                    {"RestartPolicy": self.before[name]["HostConfig"]["RestartPolicy"]},
                )
            except Exception:  # noqa: BLE001 - restore other policies after any adapter failure
                errors.append(name)
        deadline = self.clock() + self.recovery_timeout
        started = set()
        while True:
            ready = True
            for name in sorted(self.touched - set(errors)):
                try:
                    row = self._row(name)
                    if (
                        self._contract(row) != self._contract(self.before[name])
                        or row["HostConfig"]["RestartPolicy"]
                        != self.before[name]["HostConfig"]["RestartPolicy"]
                    ):
                        raise RuntimeError("Dependent configuration not preserved")
                    if not row["State"]["Running"]:
                        if name not in started:
                            started.add(name)
                            self.docker.action(row["Id"], "start")
                        ready = False
                        continue
                    # A signaled old PID may still be finishing its item. Do not
                    # claim recovery until a new process is healthy.
                    same_process = row["State"].get("StartedAt") == self.before[name][
                        "State"
                    ].get("StartedAt")
                    ready = ready and not (name in self.signaled and same_process)
                    ready = (
                        ready
                        and row["State"].get("Health", {}).get("Status") == "healthy"
                    )
                    ready = (
                        ready
                        and row["HostConfig"]["RestartPolicy"]
                        == self.before[name]["HostConfig"]["RestartPolicy"]
                    )
                except Exception:  # noqa: BLE001 - one recovery failure must not skip other workers
                    errors.append(name)
                    ready = False
            if ready and not errors:
                rows = {name: self._row(name) for name in self.before}
                self.persist(
                    "dependent-workers.restored.safe.json", self._summary(rows)
                )
                return
            if (ready and errors) or self.clock() >= deadline:
                self.persist(
                    "dependent-workers.recovery-incomplete.safe.json",
                    self._recovery_summary(errors),
                )
                raise RuntimeError(
                    "Dependent worker recovery is incomplete; inspect private receipt"
                )
            self.sleep(1)

    def __exit__(self, _kind, _error, _traceback):
        self._recover()
