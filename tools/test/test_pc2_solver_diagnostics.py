import json
import logging

import pytest

from tools import pc2_solver_diagnostics as diagnostics
from tools import pc2_solver_execution as execution


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "[SOLVER] Slider found at (120, 330) selector=secret context=token",
            {"phase": "slider_geometry", "css_x": 120.0, "css_y": 330.0},
        ),
        (
            "[SOLVER] Drag distance: 258px (track: 300px, slider: 42px)",
            {
                "phase": "drag_distance",
                "distance": 258.0,
                "track_width": 300.0,
                "slider_width": 42.0,
            },
        ),
        (
            "[SOLVER] OS mouse drag from (120,330) +258px source=x11_window_geometry located=True clipped=False profile=fast_exact_v3 input=pyautogui",
            {
                "phase": "os_drag",
                "screen_x": 120.0,
                "screen_y": 330.0,
                "distance": 258.0,
                "source": "x11_window_geometry",
                "located": True,
                "clipped": False,
                "profile": "fast_exact_v3",
                "input": "pyautogui",
            },
        ),
        (
            "[SOLVER] OS cursor position expected=(120,330) actual=(121,330) delta=1.0px",
            {
                "phase": "cursor_position",
                "expected_x": 120.0,
                "expected_y": 330.0,
                "actual_x": 121.0,
                "actual_y": 330.0,
                "delta": 1.0,
            },
        ),
        (
            "[SOLVER] Verification: success=False, sliderGone=False, challengeGone=False, hasError=True",
            {
                "phase": "verification",
                "success": False,
                "slider_gone": False,
                "challenge_gone": False,
                "has_error": True,
            },
        ),
        (
            "[SOLVER] Challenge diagnostic: code=error:300 title=secret class=secret path=https://user:secret@example.test/?token=secret retryable=True",
            {"phase": "challenge_failure", "code": "error:300", "retryable": True},
        ),
        (
            "[SOLVER] Challenge diagnostic: code=error:secret title=secret class=secret path=secret retryable=False",
            {"phase": "challenge_failure", "code": "other", "retryable": False},
        ),
        ("[SOLVER] Drag complete. Verifying...", {"phase": "drag_complete"}),
        ("[SOLVER] Verified: Captcha solved", {"phase": "verified"}),
    ],
)
def test_only_allowlisted_fields_are_published(message, expected):
    event = diagnostics.diagnostic_event(message)
    assert event == {"kind": "local_solver_diagnostic", **expected}
    assert "secret" not in json.dumps(event)


@pytest.mark.parametrize(
    "message",
    [
        "[SOLVER] Found target: https://example.test/?token=secret",
        "[SOLVER] Drag distance: nanpx (track: 300px, slider: 42px)",
        "[SOLVER] Verification: success=secret, sliderGone=False, challengeGone=False, hasError=True",
        "[SOLVER] Verified: Captcha solved\nsecret",
        "[SOLVER] " + "secret" * 1000,
    ],
)
def test_unknown_or_malformed_messages_fail_closed(message):
    assert diagnostics.diagnostic_event(message) is None


def test_unknown_profile_or_mapping_is_not_published():
    message = "[SOLVER] OS mouse drag from (1,2) +3px source=secret located=None clipped=False profile=secret input=win32"
    event = diagnostics.diagnostic_event(message)
    assert event["source"] == event["profile"] == "unknown"
    assert event["located"] is None
    assert "secret" not in json.dumps(event)


def test_actual_slider_verification_log_is_admitted(monkeypatch):
    from src.captcha_solver import CaptchaSolver

    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    solver = CaptchaSolver(target_url="https://example.invalid/")
    solver._send_cdp = lambda *args, **kwargs: {
        "result": {
            "value": {
                "success": False,
                "sliderGone": False,
                "challengeGone": False,
                "hasError": True,
            }
        }
    }
    solver._is_authenticated_auction_page = lambda: False
    with diagnostics.solver_attempt_diagnostics():
        assert not solver._verify_success()
    assert events == [
        {
            "kind": "local_solver_diagnostic",
            "phase": "verification",
            "success": False,
            "slider_gone": False,
            "challenge_gone": False,
            "has_error": True,
        }
    ]


def test_child_entry_publishes_diagnostics_and_restores_logging(monkeypatch):
    events = []
    records = []
    logger = logging.getLogger("src.captcha_orchestration")
    original_level, original_filters = logger.level, logger.filters[:]
    root = logging.getLogger()
    root_state = root.level, root.handlers[:]

    class Sink(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    class Connection:
        result = None
        closed = False

        def send(self, value):
            self.result = value

        def close(self):
            self.closed = True

    sink = Sink()
    logger.addHandler(sink)
    logger.setLevel(logging.WARNING)
    monkeypatch.setattr(diagnostics, "log_event", events.append)

    def fake_run(*args, **kwargs):
        logger.info(
            "[SOLVER] Drag distance: %.0fpx (track: %.0fpx, slider: %.0fpx)",
            258,
            300,
            42,
        )
        logger.info("[SOLVER] Found target: secret")
        logger.warning("[SOLVER] Verification failed; reloading and retrying")
        return False

    monkeypatch.setattr(execution, "run_solver_local", fake_run)
    connection = Connection()
    try:
        execution._run_solver_process_entry(
            connection, "offline", "offline", 1, None, 0
        )
        assert connection.result == {"success": False} and connection.closed
        assert len(events) == 1 and events[0]["phase"] == "drag_distance"
        assert records == ["[SOLVER] Verification failed; reloading and retrying"]
        assert logger.level == logging.WARNING and logger.filters == original_filters
        assert (root.level, root.handlers) == root_state
    finally:
        logger.removeHandler(sink)
        logger.setLevel(original_level)


def test_telemetry_failure_does_not_interrupt_solver_or_leak_info(monkeypatch, caplog):
    def broken_sink(event):
        raise OSError("diagnostic output unavailable")

    monkeypatch.setattr(diagnostics, "log_event", broken_sink)
    with caplog.at_level(logging.INFO), diagnostics.solver_attempt_diagnostics():
        logging.getLogger("src.captcha_slider").info(
            "[SOLVER] Verified: Captcha solved"
        )
        logging.getLogger("src.captcha_slider").info("secret")
        logging.getLogger("src.captcha_slider").warning("retained warning")
    assert caplog.messages == ["retained warning"]


def test_diagnostics_are_bounded_per_phase_and_restored_on_error(monkeypatch):
    events = []
    logger = logging.getLogger("src.captcha_orchestration")
    state = logger.level, logger.filters[:]
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with pytest.raises(ValueError), diagnostics.solver_attempt_diagnostics():
        for _ in range(1000):
            logger.info("[SOLVER] Drag complete. Verifying...")
        logger.info("[SOLVER] Verified: Captcha solved")
        raise ValueError("offline failure")
    assert len(events) == 65 and events[-1]["phase"] == "verified"
    assert (logger.level, logger.filters) == state
