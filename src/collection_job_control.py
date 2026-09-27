"""Cooperative stop boundaries shared by queued operations and maintenance stages."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_TIMEOUT_SECONDS = 1800.0


class JobStopped(BaseException):
    """A stop request must cross legacy business-error fallback handlers."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def positive_timeout(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError("Collection job timeout must be finite and positive")
    return float(value)


class JobControl:
    def __init__(self, timeout_seconds: float) -> None:
        self.deadline = time.monotonic() + positive_timeout(timeout_seconds)
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason: str | None = None

    def request_stop(self, reason: str) -> None:
        with self._lock:
            if self._reason is None:
                self._reason = reason
                self._event.set()

    def stop_reason(self) -> str | None:
        with self._lock:
            if self._reason is None and time.monotonic() >= self.deadline:
                self._reason = "timed_out"
                self._event.set()
            return self._reason

    def checkpoint(self) -> None:
        reason = self.stop_reason()
        if reason is not None:
            raise JobStopped(reason)

    def remaining(self) -> float:
        self.checkpoint()
        return max(0.001, self.deadline - time.monotonic())

    def wait(self, seconds: float) -> None:
        wake_at = time.monotonic() + max(0.0, seconds)
        while True:
            self.checkpoint()
            remaining = min(wake_at, self.deadline) - time.monotonic()
            if remaining <= 0:
                self.checkpoint()
                return
            # Recheck the monotonic boundary if the platform wait returns early.
            self._event.wait(remaining)


_CURRENT: ContextVar[JobControl | None] = ContextVar("collection_job", default=None)


@contextmanager
def job_scope(control: JobControl) -> Iterator[None]:
    token = _CURRENT.set(control)
    try:
        control.checkpoint()
        yield
        control.checkpoint()
    finally:
        _CURRENT.reset(token)


def job_checkpoint() -> None:
    control = _CURRENT.get()
    if control is not None:
        control.checkpoint()


def job_wait(seconds: float) -> None:
    control = _CURRENT.get()
    if control is None:
        time.sleep(seconds)
    else:
        control.wait(seconds)


def job_io_timeout(seconds: float) -> float:
    control = _CURRENT.get()
    return seconds if control is None else min(seconds, control.remaining())
