"""Native input ownership, not EWMH acknowledgement, decides focus readiness."""

import subprocess
from threading import Event

import pytest

from src import captcha_os_windows
from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_os_drag_fallback import physical_solve


def focused_after_lost_ack(monkeypatch, mode, *, solver=None):
    solver = solver or CaptchaSolver()
    focus = [False]
    calls = []

    def run(command, **_options):
        calls.append(command)
        operation = command[1]
        if operation == "search":
            stdout = "42\n" if command[-1] == "google-chrome" else ""
            return subprocess.CompletedProcess(command, 0, stdout)
        if operation == "getwindowfocus":
            return subprocess.CompletedProcess(command, 0, "42" if focus[0] else "99")
        if operation == "windowactivate":
            focus[0] = mode != "still_unfocused"
            if mode == "rejected":
                return subprocess.CompletedProcess(command, 1, "")
            raise subprocess.TimeoutExpired(command, 3)
        # Unneeded fallback may fail despite already-owned native focus.
        return subprocess.CompletedProcess(command, 1, "")

    monkeypatch.setattr(captcha_os_windows.subprocess, "run", run)
    monkeypatch.setenv("DISPLAY", ":99")
    return solver, calls


@pytest.mark.parametrize("mode", ["timeout", "rejected"])
def test_ack_failure_with_native_focus_needs_no_more_focus_mutations(monkeypatch, mode):
    solver, calls = focused_after_lost_ack(monkeypatch, mode)
    assert solver._activate_linux_window_id("42") is True
    assert [command[1] for command in calls] == [
        "getwindowfocus",
        "windowactivate",
        "getwindowfocus",
    ]


@pytest.mark.parametrize("mode", ["timeout", "rejected"])
@pytest.mark.parametrize("target_stays_valid", [True, False])
def test_full_focus_still_reactivates_exact_target_after_lost_ack(
    monkeypatch, mode, target_stays_valid
):
    solver, calls = focused_after_lost_ack(monkeypatch, mode)
    activations = []

    def activate_target():
        activations.append(True)
        return target_stays_valid or len(activations) == 1

    solver._activate_target_tab = activate_target
    solver._wait_interruptibly = lambda _delay: None
    assert solver._focus_linux_window() is target_stays_valid
    assert len(activations) == 2
    assert solver._linux_window_id == ("42" if target_stays_valid else None)
    assert not any(command[1] in {"windowraise", "windowfocus"} for command in calls)


def test_unowned_native_focus_still_requires_existing_fallback(monkeypatch):
    solver, calls = focused_after_lost_ack(monkeypatch, "still_unfocused")
    assert solver._activate_linux_window_id("42") is False
    assert [command[1] for command in calls][-2:] == ["windowraise", "getwindowfocus"]
    assert not any(command[1] == "windowfocus" for command in calls)


def test_interruption_during_native_recheck_never_starts_fallback(monkeypatch):
    solver, calls = focused_after_lost_ack(monkeypatch, "timeout")
    original = solver._linux_window_has_focus
    probes = []

    def check(window_id):
        probes.append(window_id)
        if len(probes) == 2:
            raise SolveStopped("cancelled")
        return original(window_id)

    solver._linux_window_has_focus = check
    with pytest.raises(SolveStopped, match="cancelled"):
        solver._activate_linux_window_id("42")
    assert [command[1] for command in calls] == ["getwindowfocus", "windowactivate"]


@pytest.mark.parametrize("mode", ["timeout", "rejected"])
@pytest.mark.parametrize("target_stays_valid", [True, False])
def test_real_solve_lost_ack_preserves_input_and_verification_guards(
    monkeypatch, mode, target_stays_valid
):
    solver, pointer = physical_solve(monkeypatch, None)
    solver, calls = focused_after_lost_ack(monkeypatch, mode, solver=solver)
    activations = []

    def activate():
        activations.append(True)
        return target_stays_valid or len(activations) == 1

    solver._activate_target_tab = activate
    solver._focus_os_window = solver._focus_linux_window
    assert solver.solve(max_attempts=1) is target_stays_valid
    assert pointer.buttons == ([True, False] if target_stays_valid else [])
    assert solver.last_failure_reason == (
        None if target_stays_valid else "execution_unavailable"
    )
    assert solver._wait_for_verification_success.call_count == int(target_stays_valid)
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()
    assert not pointer.down and not solver.lock.locked()
    assert not any(command[1] in {"windowraise", "windowfocus"} for command in calls)


def fallback_lost_ack(monkeypatch, stage, mode, owned, *, solver=None, interrupt=None):
    solver = solver or CaptchaSolver()
    focus = [False]
    calls = []

    def run(command, **_options):
        calls.append(command)
        operation = command[1]
        if operation == "search":
            stdout = "42\n" if command[-1] == "google-chrome" else ""
            return subprocess.CompletedProcess(command, 0, stdout)
        if operation == "getwindowfocus":
            return subprocess.CompletedProcess(command, 0, "42" if focus[0] else "99")
        if operation == stage:
            focus[0] = owned
            if interrupt is not None:
                interrupt()
            if mode == "timeout":
                raise subprocess.TimeoutExpired(command, 3)
            if mode == "missing":
                raise OSError("focus acknowledgement unavailable")
            return subprocess.CompletedProcess(command, 1, "")
        return subprocess.CompletedProcess(command, 0, "")

    monkeypatch.setattr(captcha_os_windows.subprocess, "run", run)
    monkeypatch.setenv("DISPLAY", ":99")
    return solver, calls


@pytest.mark.parametrize("stage", ["windowraise", "windowfocus"])
@pytest.mark.parametrize("mode", ["timeout", "rejected", "missing"])
@pytest.mark.parametrize("owned", [True, False])
def test_fallback_ack_failure_requires_native_focus_proof(
    monkeypatch, stage, mode, owned
):
    solver, calls = fallback_lost_ack(monkeypatch, stage, mode, owned)
    assert solver._activate_linux_window_id("42") is owned
    assert calls[-1][1] == "getwindowfocus"
    if stage == "windowraise":
        assert not any(command[1] == "windowfocus" for command in calls)


@pytest.mark.parametrize("stage", ["windowraise", "windowfocus"])
@pytest.mark.parametrize("mode", ["timeout", "rejected"])
def test_fallback_ack_loss_never_swallows_cancellation(monkeypatch, stage, mode):
    event = Event()
    solver, calls = fallback_lost_ack(
        monkeypatch, stage, mode, True, interrupt=event.set
    )
    solver._solve_budget = SolveBudget(cancel_event=event)
    with pytest.raises(SolveStopped, match="cancelled"):
        solver._activate_linux_window_id("42")
    assert calls[-1][1] == stage
    assert solver.last_failure_reason == "cancelled"


@pytest.mark.parametrize("mode", ["timeout", "rejected"])
@pytest.mark.parametrize("target_stays_valid", [True, False])
def test_real_solve_fallback_ack_loss_keeps_exact_target_guard(
    monkeypatch, mode, target_stays_valid
):
    solver, pointer = physical_solve(monkeypatch, None)
    solver, calls = fallback_lost_ack(
        monkeypatch, "windowfocus", mode, True, solver=solver
    )
    activations = []

    def activate():
        activations.append(True)
        return target_stays_valid or len(activations) == 1

    solver._activate_target_tab = activate
    solver._focus_os_window = solver._focus_linux_window
    assert solver.solve(max_attempts=1) is target_stays_valid
    assert pointer.buttons == ([True, False] if target_stays_valid else [])
    assert solver.last_failure_reason == (
        None if target_stays_valid else "execution_unavailable"
    )
    assert solver._wait_for_verification_success.call_count == int(target_stays_valid)
    solver._do_drag.assert_not_called()
    solver._reload_page.assert_not_called()
    assert not pointer.down and not solver.lock.locked()
    assert any(command[1] == "windowfocus" for command in calls)
