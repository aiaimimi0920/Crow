from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

import pytest

from src import (
    captcha_nc_retry,
    captcha_os_input,
    captcha_os_mapping,
    captcha_os_windows,
)
from src.captcha_budget import SolveBudget


def set_solver_platform(monkeypatch, name):
    platform_os = SimpleNamespace(**{**vars(os), "name": name})
    for module in (captcha_nc_retry, captcha_os_input, captcha_os_mapping, captcha_os_windows):
        monkeypatch.setattr(module, "os", platform_os)


@pytest.fixture(autouse=True)
def _inject_solver_test_waits(monkeypatch):
    """Keep legacy mocked sleep clocks explicit; deadline tests use the real Event."""
    now = [time.monotonic()]

    class TestWaitEvent(threading.Event):
        def wait(self, timeout=None):
            if not self.is_set():
                time.sleep(timeout or 0)
                now[0] += timeout or 0
            return self.is_set()

    class TestSolveBudget(SolveBudget):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, clock=lambda: now[0])

    monkeypatch.setattr("src.captcha_budget.Event", TestWaitEvent)
    monkeypatch.setattr("src.captcha_budget.SolveBudget", TestSolveBudget)


__all__ = ["_inject_solver_test_waits", "set_solver_platform"]
