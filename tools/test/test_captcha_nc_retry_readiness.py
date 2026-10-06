"""NC retry input requires verified focus and consecutive ready samples."""

import sys
from types import SimpleNamespace

import pytest

from src import captcha_nc_retry, captcha_solver
from src.captcha_budget import SolveStopped


@pytest.mark.parametrize("focus_result", [False, RuntimeError("focus API failed")])
def test_retry_click_skips_all_input_when_window_focus_fails(monkeypatch, focus_result):
    events = []
    monkeypatch.setitem(
        sys.modules, "pyautogui", SimpleNamespace(FAILSAFE=True, PAUSE=0)
    )
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._os_mouse_enabled = lambda: True

    def focus():
        if isinstance(focus_result, Exception):
            raise focus_result
        return focus_result

    solver._focus_os_window = focus
    solver._map_css_to_screen = lambda *a, **k: (
        events.append("mapping") or {"x": 100, "y": 50, "source": "test"}
    )
    solver._move_os_cursor_bounded = lambda *a: events.append("move")
    solver._set_os_left_button = lambda *a, **k: events.append("button")
    solver._dispatch_mouse = lambda *a, **k: events.append("cdp") or True
    solver._wait_interruptibly = lambda *a: None

    assert solver._click_css_point(100, 50) is False
    assert solver.last_failure_reason == "window_focus_failed"
    assert events == []


def test_retry_click_preserves_cooperative_stop_from_focus(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "pyautogui", SimpleNamespace(FAILSAFE=True, PAUSE=0)
    )
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._os_mouse_enabled = lambda: True

    def focus():
        raise SolveStopped("cancelled")

    solver._focus_os_window = focus
    with pytest.raises(SolveStopped, match="cancelled"):
        solver._click_css_point(100, 50)
    assert solver.last_failure_reason is None


def retry_probe(monkeypatch, samples, summaries=None):
    solver = captcha_solver.CaptchaSolver(port=9223)
    clock = [0.0]
    calls = []
    samples = iter(samples)
    summaries = iter(summaries or [])
    monkeypatch.setattr(captcha_nc_retry.time, "time", lambda: clock[0])
    solver._wait_interruptibly = lambda seconds: clock.__setitem__(
        0, clock[0] + seconds
    )
    solver._refresh_challenge_summary = lambda _: next(summaries, {})

    def find_slider(**kwargs):
        calls.append(kwargs)
        return next(samples, None)

    solver._find_slider = find_slider
    return solver, calls


SLIDER = {"x": 100, "y": 200, "width": 42, "height": 30}


def test_retry_readiness_restarts_consecutive_count_after_missing_slider(monkeypatch):
    solver, calls = retry_probe(monkeypatch, [SLIDER, None, SLIDER, SLIDER, SLIDER])
    assert solver._nc_retry_outcome(timeout_seconds=2.0)["slider"] == SLIDER
    assert len(calls) == 5
    assert all(call == {"max_retries": 1, "retry_delay": 0} for call in calls)


def test_retry_readiness_rejects_nonconsecutive_samples_within_deadline(monkeypatch):
    solver, calls = retry_probe(monkeypatch, [SLIDER, None, SLIDER, None, SLIDER])
    assert solver._nc_retry_outcome(timeout_seconds=1.5) == {"authenticated": False}
    assert len(calls) == 5


def test_retry_readiness_restarts_count_after_explicit_failure(monkeypatch):
    solver, calls = retry_probe(
        monkeypatch, [SLIDER] * 5, [{}, {}, {"explicitFailure": True}, {}, {}, {}]
    )
    assert solver._nc_retry_outcome(timeout_seconds=2.0)["slider"] == SLIDER
    assert len(calls) == 5


def test_retry_readiness_still_accepts_authenticated_page_without_slider(monkeypatch):
    summary = {"authenticatedPage": True}
    solver, calls = retry_probe(monkeypatch, [], [summary])
    assert solver._nc_retry_outcome() == {"authenticated": True, "summary": summary}
    assert calls == []


def test_retry_readiness_stops_before_probing_after_cancellation(monkeypatch):
    solver, calls = retry_probe(monkeypatch, [SLIDER] * 3)
    solver._stop_if_cancelled = lambda: True
    assert solver._nc_retry_outcome() == {"cancelled": True}
    assert calls == []
