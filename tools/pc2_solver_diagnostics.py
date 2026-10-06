"""Bounded, allowlisted INFO telemetry for the isolated solver attempt."""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager

from tools.pc2_solver_transport import log_event

_LOGGERS = (
    "src.captcha_orchestration",
    "src.captcha_os_input",
    "src.captcha_slider",
)
_NUMBER = r"-?\d{1,6}(?:\.\d{1,3})?"
_BOOL = r"True|False|None"
_PATTERNS = (
    (
        "slider_geometry",
        rf"\[SOLVER\] Slider found at \((?P<css_x>{_NUMBER}), (?P<css_y>{_NUMBER})\) selector=.* context=.*",
    ),
    (
        "drag_distance",
        rf"\[SOLVER\] Drag distance: (?P<distance>{_NUMBER})px \(track: (?P<track_width>{_NUMBER})px, slider: (?P<slider_width>{_NUMBER})px\)",
    ),
    (
        "os_drag",
        (
            rf"\[SOLVER\] OS mouse drag from \((?P<screen_x>{_NUMBER}),(?P<screen_y>{_NUMBER})\) \+(?P<distance>{_NUMBER})px "
            rf"source=(?P<source>[a-z0-9_]{{1,40}}) located=(?P<located>{_BOOL}) clipped=(?P<clipped>{_BOOL}) "
            r"profile=(?P<profile>[a-z0-9_]{1,40}) input=(?P<input>uinput|win32|pyautogui)"
        ),
    ),
    (
        "cursor_position",
        (
            rf"\[SOLVER\] OS cursor position expected=\((?P<expected_x>{_NUMBER}),(?P<expected_y>{_NUMBER})\) "
            rf"actual=\((?P<actual_x>{_NUMBER}),(?P<actual_y>{_NUMBER})\) delta=(?P<delta>{_NUMBER})px"
        ),
    ),
    (
        "verification",
        (
            rf"\[SOLVER\] (?:\[SOLVER\] )?Verification: success=(?P<success>{_BOOL}), sliderGone=(?P<slider_gone>{_BOOL}), "
            rf"challengeGone=(?P<challenge_gone>{_BOOL}), hasError=(?P<has_error>{_BOOL})"
        ),
    ),
    (
        "challenge_failure",
        rf"\[SOLVER\] Challenge diagnostic: code=(?P<code>[^ ]{{1,80}}) title=.* class=.* path=.* retryable=(?P<retryable>{_BOOL})",
    ),
)
_ENUMS = {
    "source": {
        "x11_window_geometry",
        "screenshot_handle",
        "screenshot_viewport",
        "cdp_window_bounds",
        "win32_render",
        "win32_client",
        "dpr_fallback",
    },
    "profile": {"fast_exact_v3", "legacy_exact_release", "dense_exact_release"},
    "input": {"uinput", "win32", "pyautogui"},
}
_BOOLEANS = {
    "located",
    "clipped",
    "success",
    "slider_gone",
    "challenge_gone",
    "has_error",
    "retryable",
}
_FIXED = {
    "[SOLVER] Drag complete. Verifying...": "drag_complete",
    "[SOLVER] Verified: Captcha solved": "verified",
}


def diagnostic_event(message: str) -> dict[str, object] | None:
    """Never publish page text, selectors, URLs, exception text or opaque tokens."""
    if len(message) > 1000:
        return None
    phase = _FIXED.get(message)
    if phase:
        return {"kind": "local_solver_diagnostic", "phase": phase}
    for phase, pattern in _PATTERNS:
        match = re.fullmatch(pattern, message)
        if not match:
            continue
        event: dict[str, object] = {"kind": "local_solver_diagnostic", "phase": phase}
        for key, value in match.groupdict().items():
            if key in _BOOLEANS:
                event[key] = None if value == "None" else value == "True"
            elif key in _ENUMS:
                event[key] = value if value in _ENUMS[key] else "unknown"
            elif key == "code":
                event[key] = (
                    value if re.fullmatch(r"error:\d{1,6}|none", value) else "other"
                )
            else:
                event[key] = float(value)
        return event
    return None


class _DiagnosticFilter(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self.counts: Counter[str] = Counter()

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.INFO:
            return True
        try:
            event = diagnostic_event(record.getMessage())
            if event:
                phase = str(event["phase"])
                if self.counts[phase] < 64:
                    self.counts[phase] += 1
                    log_event(event)
        except Exception:  # noqa: BLE001 -- telemetry must not change solve or cleanup behavior
            return False
        # No raw INFO record reaches existing handlers, even with an INFO root.
        return False


@contextmanager
def solver_attempt_diagnostics() -> Iterator[None]:
    """Scope INFO admission to this child; retain WARNING handlers and root state."""
    diagnostic_filter = _DiagnosticFilter()
    loggers = [logging.getLogger(name) for name in _LOGGERS]
    levels = [logger.level for logger in loggers]
    try:
        for logger in loggers:
            logger.addFilter(diagnostic_filter)
            logger.setLevel(logging.INFO)
        yield
    finally:
        for logger, level in zip(loggers, levels, strict=True):
            logger.setLevel(level)
            logger.removeFilter(diagnostic_filter)
