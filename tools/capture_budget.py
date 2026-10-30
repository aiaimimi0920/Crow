"""Cooperative operation budget inside the owned helper's hard deadline."""

import math
import time
from contextlib import contextmanager
from contextvars import ContextVar

_DEADLINE = ContextVar("capture_connection_deadline", default=None)


class CaptureBudgetExceeded(TimeoutError):
    def __init__(self):
        super().__init__("detail capture operation budget exhausted")


@contextmanager
def capture_budget(deadline):
    if deadline is not None and (
        type(deadline) not in (int, float) or not math.isfinite(deadline)
    ):
        raise ValueError("Invalid detail capture connection deadline")
    token = _DEADLINE.set(deadline)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def _remaining_seconds():
    deadline = _DEADLINE.get()
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CaptureBudgetExceeded()
    return remaining


def check_capture_budget():
    _remaining_seconds()


def bounded_capture_timeout(timeout_ms):
    remaining = _remaining_seconds()
    if remaining is None:
        return timeout_ms
    available_ms = max(1, math.floor(remaining * 1000))
    return available_ms if timeout_ms == 0 else min(timeout_ms, available_ms)


def bounded_connect_timeout(timeout_ms):
    return bounded_capture_timeout(timeout_ms)


def bounded_http_timeout(timeout_seconds):
    remaining = _remaining_seconds()
    return timeout_seconds if remaining is None else min(timeout_seconds, remaining)


def wait_for_cdp_retry(seconds):
    remaining = _remaining_seconds()
    if remaining is not None and seconds >= remaining:
        time.sleep(remaining)
        raise CaptureBudgetExceeded()
    time.sleep(seconds)
