"""Bounded, allowlisted INFO telemetry for the isolated solver attempt."""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager

from tools.pc2_solver_transport import log_event
from tools.solver_binding_evidence import BINDING_ENUMS

_LOGGERS = (
    "src.captcha_orchestration",
    "src.captcha_os_input",
    "src.captcha_slider",
    "src.captcha_nc_retry",
    "src.captcha_preflight",
)
_NUMBER = r"-?\d{1,6}(?:\.\d{1,3})?"
_BOOL = r"True|False|None"
_PATTERNS = (
    (
        "target_binding",
        (
            r"\[SOLVER\] Target binding: stage=(?P<stage>[a-z_]{1,24}) binding=(?P<binding>[a-z_]{1,24}) "
            r"location_code=(?P<location_code>[a-z_]{1,24}) st_param=(?P<st_param>[a-z_]{1,24}) "
            r"auction_start_seg=(?P<auction_start_seg>[a-z_]{1,24}) page=(?P<page>[a-z_]{1,24})"
            r"(?: navigation_probe=(?P<navigation_probe>[a-z_]{1,24})"
            r" navigation_frame=(?P<navigation_frame>[a-z_]{1,24})"
            r" navigation_loader=(?P<navigation_loader>[a-z_]{1,24})"
            r" navigation_url=(?P<navigation_url>[a-z_]{1,24}))?"
            r"(?: navigation_capture=(?P<navigation_capture>[a-z_]{1,24})"
            r" navigation_origin=(?P<navigation_origin>[a-z_]{1,24})"
            r" navigation_transition=(?P<navigation_transition>[a-z_]{1,24})"
            r" navigation_commit=(?P<navigation_commit>[a-z_]{1,24})"
            r" navigation_flow_loader=(?P<navigation_flow_loader>[a-z_]{1,24})"
            r" navigation_flow_pending=(?P<navigation_flow_pending>[a-z_]{1,24}))?"
        ),
    ),
    (
        "nc_retry_click",
        (
            r"\[SOLVER\] Clicking NC retry target (?P<candidate_index>\d{1,2})/(?P<candidate_count>\d{1,2}) "
            rf"\((?P<candidate_kind>widget_centerline|widget_vertical|retry_text|widget_fallback)\) at \({_NUMBER},{_NUMBER}\)"
        ),
    ),
    (
        "slider_missing",
        (
            r"\[SOLVER\] Slider unavailable: ready=(?P<ready_state>loading|interactive|complete|unknown) "
            rf"probeFailed=(?P<probe_failed>{_BOOL}) targetReady=(?P<target_ready>{_BOOL}) "
            rf"challengePresent=(?P<challenge_present>{_BOOL}) loginRequired=(?P<login_required>{_BOOL}) "
            rf"hardBlock=(?P<hard_block>{_BOOL}) explicitFailure=(?P<explicit_failure>{_BOOL}) "
            rf"authenticatedPage=(?P<authenticated_page>{_BOOL})"
        ),
    ),
    (
        "pointer_failure",
        r"\[SOLVER\] OS pointer probe failed reason=(?P<reason>[a-z_]{1,40}) check=(?P<check>[a-z_]{1,40})",
    ),
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
        "pointer_hit",
        rf"\[SOLVER\] OS pointer hit verified delta=(?P<delta>{_NUMBER})px corrections=(?P<corrections>\d{{1,2}})",
    ),
    (
        "drag_timing",
        rf"\[SOLVER\] OS drag timing movement=(?P<movement_seconds>{_NUMBER})s hold=(?P<hold_seconds>{_NUMBER})s",
    ),
    (
        "input_receipt",
        (
            rf"\[SOLVER\] OS input receipt backendCompleted=(?P<backend_completed>{_BOOL}) "
            rf"pressSeen=(?P<press_seen>{_BOOL}) pressOnTarget=(?P<press_on_target>{_BOOL}) "
            rf"pressedMoves=(?P<pressed_moves>\d{{1,5}}) releaseSeen=(?P<release_seen>{_BOOL}) "
            rf"documentCurrent=(?P<document_current>{_BOOL})"
        ),
    ),
    (
        "input_receipt_unavailable",
        rf"\[SOLVER\] OS input receipt unavailable backendCompleted=(?P<backend_completed>{_BOOL})",
    ),
    (
        "verification",
        (
            rf"\[SOLVER\] (?:\[SOLVER\] )?Verification: success=(?P<success>{_BOOL}), sliderGone=(?P<slider_gone>{_BOOL}), "
            rf"challengeGone=(?P<challenge_gone>{_BOOL}), hasError=(?P<has_error>{_BOOL})"
            rf"(?:, errorText=(?P<error_text>{_BOOL}), errorWidget=(?P<error_widget>{_BOOL}))?"
        ),
    ),
    (
        "challenge_failure",
        (
            r"\[SOLVER\] Challenge diagnostic: code=(?P<code>[^ ]{1,80}) "
            r"codeKind=(?P<code_kind>[a-z_]{1,20}) ready=(?P<ready_state>[a-z_]{1,20}) "
            rf"targetReady=(?P<target_ready>{_BOOL}) probeFailed=(?P<probe_failed>{_BOOL}) "
            rf"retryable=(?P<retryable>{_BOOL})"
        ),
    ),
    (
        "challenge_failure",
        rf"\[SOLVER\] Challenge diagnostic: code=(?P<code>[^ ]{{1,80}}) title=.* class=.* path=.* retryable=(?P<retryable>{_BOOL})",
    ),
)
_ENUMS = {
    **BINDING_ENUMS,
    "candidate_kind": {
        "widget_centerline",
        "widget_vertical",
        "retry_text",
        "widget_fallback",
    },
    "ready_state": {"loading", "interactive", "complete", "unknown"},
    "code_kind": {"absent", "numeric", "opaque", "invalid"},
    "reason": {
        "target_unavailable",
        "target_invalid",
        "target_changed",
        "pointer_unobserved",
        "pointer_changed",
        "pointer_missed",
    },
    "check": {
        "target",
        "open_native_focus",
        "open_snapshot",
        "open_binding",
        "binding_missing",
        "binding_document",
        "binding_expired",
        "binding_changed",
        "node_unavailable",
        "frame_unavailable",
        "track_unavailable",
        "native_focus",
        "snapshot",
        "event_buttons",
        "event_serial",
        "event_age",
    },
    "source": {
        "x11_window_geometry",
        "screenshot_handle",
        "screenshot_viewport",
        "cdp_window_bounds",
        "win32_render",
        "win32_client",
        "dpr_fallback",
    },
    "profile": {
        "fast_exact_v3",
        "legacy_exact_release",
        "dense_exact_release",
        "slow_exact_v4",
        "slow_settle_v4",
        "slow_dense_v4",
    },
    "input": {"uinput", "win32", "pyautogui"},
}
_BOOLEANS = {
    "backend_completed",
    "press_seen",
    "press_on_target",
    "release_seen",
    "document_current",
    "probe_failed",
    "target_ready",
    "challenge_present",
    "login_required",
    "hard_block",
    "explicit_failure",
    "authenticated_page",
    "located",
    "clipped",
    "success",
    "slider_gone",
    "challenge_gone",
    "has_error",
    "error_text",
    "error_widget",
    "retryable",
}
_FIXED = {
    "[SOLVER] Drag complete. Verifying...": "drag_complete",
    "[SOLVER] Verified: Captcha solved": "verified",
    "[SOLVER] NC slider restored after retry click.": "nc_retry_restored",
    "[SOLVER] NC retry click recovered an authenticated page.": "nc_retry_authenticated",
    "[SOLVER] NC retry document uncertain; deferring without further clicks.": "nc_retry_uncertain",
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
            if value is None:
                continue
            if key in _BOOLEANS:
                event[key] = None if value == "None" else value == "True"
            elif key in _ENUMS:
                event[key] = (
                    value
                    if value in _ENUMS[key]
                    else ("invalid" if key == "code_kind" else "unknown")
                )
            elif key == "code":
                event[key] = (
                    value if re.fullmatch(r"error:[0-9]{1,6}|none", value) else "other"
                )
            elif key in {"candidate_index", "candidate_count", "pressed_moves"}:
                event[key] = int(value)
            else:
                event[key] = float(value)
        if phase == "nc_retry_click" and not (
            1 <= event["candidate_index"] <= event["candidate_count"] <= 16
        ):
            return None
        if phase == "input_receipt" and event["pressed_moves"] > 10000:
            return None
        return event
    return None


class _DiagnosticFilter(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self.counts: Counter[str] = Counter()
        self.pending_drag = False
        self.failed_drag_verifications = 0

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.INFO:
            return True
        try:
            event = diagnostic_event(record.getMessage())
            if event:
                phase = str(event["phase"])
                if phase == "drag_complete":
                    self.pending_drag = True
                elif phase == "verification" and self.pending_drag:
                    if event.get("success") is False:
                        self.failed_drag_verifications += 1
                    self.pending_drag = False
                if self.counts[phase] < 64:
                    self.counts[phase] += 1
                    log_event(event)
        except Exception:  # noqa: BLE001 -- telemetry must not change solve or cleanup behavior
            return False
        # No raw INFO record reaches existing handlers, even with an INFO root.
        return False


@contextmanager
def solver_attempt_diagnostics() -> Iterator[_DiagnosticFilter]:
    """Scope INFO admission to this child; retain WARNING handlers and root state."""
    diagnostic_filter = _DiagnosticFilter()
    loggers = [logging.getLogger(name) for name in _LOGGERS]
    levels = [logger.level for logger in loggers]
    try:
        for logger in loggers:
            logger.addFilter(diagnostic_filter)
            logger.setLevel(logging.INFO)
        yield diagnostic_filter
    finally:
        for logger, level in zip(loggers, levels, strict=True):
            logger.setLevel(level)
            logger.removeFilter(diagnostic_filter)
