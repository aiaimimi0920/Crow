"""Xwayland input focus can succeed without an EWMH activation acknowledgement."""

import subprocess
import time

import pytest

from src import captcha_solver


@pytest.mark.parametrize(
    "mode", ["timeout", "rejected", "already_focused", "wrong_focus", "target_changed"]
)
def test_linux_focus_requires_verified_browser_input_focus(monkeypatch, mode):
    calls = []
    activations = []
    focus = "101" if mode == "already_focused" else "999"

    def run(command, **_kwargs):
        nonlocal focus
        calls.append(tuple(command))
        operation = command[1]
        if operation == "search":
            return subprocess.CompletedProcess(
                command, 0, "101\n" if command[-1] == "chromium" else "", ""
            )
        if operation == "windowactivate":
            if mode == "rejected":
                return subprocess.CompletedProcess(command, 1, "", "")
            raise subprocess.TimeoutExpired(command, 3)
        if operation == "windowfocus" and mode != "wrong_focus":
            focus = "101"
        return subprocess.CompletedProcess(
            command, 0, focus + "\n" if operation == "getwindowfocus" else "", ""
        )

    def activate_target():
        activations.append(1)
        return mode != "target_changed" or len(activations) == 1

    solver = captcha_solver.CaptchaSolver(port=9223)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(solver, "_activate_target_tab", activate_target)
    expected = mode not in {"wrong_focus", "target_changed"}
    assert solver._focus_linux_window() is expected
    assert solver._linux_window_id == ("101" if expected else None)
    if mode == "already_focused":
        assert not any(call[1] in {"windowactivate", "windowfocus"} for call in calls)
    elif expected:
        assert ("xdotool", "windowraise", "101") in calls
        assert ("xdotool", "windowfocus", "--sync", "101") in calls
        assert len(activations) == 2
