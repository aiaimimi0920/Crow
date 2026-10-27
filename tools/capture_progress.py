"""Bounded, fixed capture phases; never serialize browser inputs or error text."""

import math
import re
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar

_ENABLED = ContextVar("capture_progress_enabled", default=False)
_STAGES = frozenset(
    {
        "helper_import",
        "capture_start",
        "driver_start",
        "cdp_connect",
        "existing_pages",
        "existing_page_read",
        "page_create",
        "page_session",
        "page_configure",
        "page_navigate",
        "detail_ready",
        "page_session_detach",
        "page_close",
        "browser_detach",
        "driver_stop",
        "reply_write",
    }
)
_MARKER = re.compile(rb"(?m)^CROW_CAPTURE_PHASE:v1 ([a-z_]+) ([0-9]+\.[0-9]+)\r?\n")


@contextmanager
def capture_progress():
    token = _ENABLED.set(True)
    try:
        yield
    finally:
        _ENABLED.reset(token)


def mark_capture_stage(stage):
    if not _ENABLED.get() or type(stage) is not str or stage not in _STAGES:
        return
    try:
        if sys.stderr is not None:
            sys.stderr.write(f"CROW_CAPTURE_PHASE:v1 {stage} {time.monotonic():.9f}\n")
            sys.stderr.flush()
    except (OSError, ValueError):
        # Diagnostic I/O must not replace the capture outcome.
        pass


@contextmanager
def capture_driver(factory):
    mark_capture_stage("driver_start")
    with factory() as driver:
        try:
            yield driver
        finally:
            mark_capture_stage("driver_stop")


def safe_capture_progress(value):
    if not isinstance(value, dict):
        return {}
    stage, seconds = value.get("stage"), value.get("stage_elapsed_seconds")
    if (
        type(stage) is not str
        or stage not in _STAGES
        or type(seconds) not in (int, float)
        or seconds < 0
    ):
        return {}
    try:
        if not math.isfinite(seconds):
            return {}
    except OverflowError:
        return {}
    return {"stage": stage, "stage_elapsed_seconds": round(seconds, 3)}


def parse_capture_progress(raw, *, started_at, observed_at):
    if not isinstance(raw, bytes) or not (
        math.isfinite(started_at) and math.isfinite(observed_at)
    ):
        return {}
    progress = {}
    # communicate already drains stderr. Inspect only a small tail, never return it.
    for match in _MARKER.finditer(raw[-16_384:]):
        stamp = float(match[2])
        if not math.isfinite(stamp) or not started_at <= stamp <= observed_at:
            continue
        candidate = safe_capture_progress(
            {
                "stage": match[1].decode("ascii"),
                "stage_elapsed_seconds": observed_at - stamp,
            }
        )
        if candidate:
            progress = candidate
    return progress


class CaptureDeadlineExceeded(TimeoutError):
    def __init__(self, progress):
        super().__init__("detail browser capture deadline exceeded")
        self.progress = safe_capture_progress(progress)
