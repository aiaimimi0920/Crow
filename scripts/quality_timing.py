"""Optional, payload-free pytest timing checkpoints for the isolated runner."""

import json
import os
import time
from pathlib import Path

import pytest


class TimingReport:
    def __init__(self, path: Path):
        self.path = path
        self.started = time.perf_counter()
        self.loop_started = None
        self.data = {
            "complete": False,
            "stage": "configured",
            "collection_seconds": None,
            "test_loop_seconds": None,
            "phase_seconds": dict.fromkeys(("setup", "call", "teardown"), 0.0),
            "phase_counts": dict.fromkeys(("setup", "call", "teardown"), 0),
            "files": {},
            "completed_tests": 0,
        }

    def checkpoint(self):
        self.data["session_seconds"] = time.perf_counter() - self.started
        if self.loop_started is not None:
            self.data["test_loop_seconds"] = time.perf_counter() - self.loop_started
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    @pytest.hookimpl(wrapper=True)
    def pytest_collection(self, session):
        started = time.perf_counter()
        self.data["stage"] = "collection"
        self.checkpoint()
        try:
            return (yield)
        finally:
            self.data["collection_seconds"] = time.perf_counter() - started
            self.data["collected_tests"] = len(session.items)
            self.checkpoint()

    @pytest.hookimpl(wrapper=True)
    def pytest_runtestloop(self, session):
        started = time.perf_counter()
        self.loop_started = started
        self.data["stage"] = "test_loop"
        self.checkpoint()
        try:
            return (yield)
        finally:
            self.data["test_loop_seconds"] = time.perf_counter() - started
            self.loop_started = None
            self.checkpoint()

    def pytest_runtest_logreport(self, report):
        phase = report.when
        self.data["phase_seconds"][phase] += report.duration
        self.data["phase_counts"][phase] += 1
        # Exclude parameter IDs, assertion messages, captured output and environment.
        filename = report.nodeid.split("::", 1)[0]
        row = self.data["files"].setdefault(filename, {"seconds": 0.0, "phases": 0})
        row["seconds"] += report.duration
        row["phases"] += 1
        self.data["last_phase"] = {"file": filename, "phase": phase}
        if phase == "teardown":
            self.data["completed_tests"] += 1
            if self.data["completed_tests"] % 50 == 0:
                self.checkpoint()

    def pytest_sessionfinish(self, session, exitstatus):
        self.data["complete"] = True
        self.data["stage"] = "finished"
        self.data["exit_status"] = int(exitstatus)
        self.checkpoint()


def pytest_configure(config):
    path = os.environ.get("CROW_QUALITY_TIMING_REPORT")
    if path:
        report = TimingReport(Path(path))
        config.pluginmanager.register(report, "crow-quality-timing-report")
        report.checkpoint()
