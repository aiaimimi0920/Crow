"""Native X11 probes share the solve deadline and never accept late focus proof."""

import subprocess
from threading import Event
from types import SimpleNamespace

import pytest

from src import captcha_os_windows
from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver

OPERATIONS = (
    ("_linux_window_has_focus", ("42",)),
    ("_activate_linux_window_id", ("42",)),
    ("_linux_window_geometry", ()),
    ("_linux_window_frame_extents", ()),
)


def window_probe(monkeypatch, *, budgeted=True, after_run=None):
    now = [100.0]
    event = Event()
    solver = CaptchaSolver()
    solver._linux_window_id = "42"
    solver._activate_target_tab = lambda: True
    if budgeted:
        solver._solve_budget = SolveBudget(
            deadline=102.0, cancel_event=event, clock=lambda: now[0]
        )
    monkeypatch.setattr(
        captcha_os_windows,
        "os",
        SimpleNamespace(name="posix", environ={"DISPLAY": ":99"}),
    )
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if after_run:
            after_run(now, event, command, kwargs)
        if command[0] == "xwininfo":
            text = (
                "Absolute upper-left X: 100\nAbsolute upper-left Y: 200\n"
                "Width: 800\nHeight: 600\n"
            )
        elif command[0] == "xprop":
            text = "_NET_FRAME_EXTENTS(CARDINAL) = 1, 1, 20, 1\n"
        else:
            text = "42\n"
        return SimpleNamespace(returncode=0, stdout=text)

    monkeypatch.setattr(captcha_os_windows.subprocess, "run", run)
    return solver, now, event, calls


@pytest.mark.parametrize("method,args", OPERATIONS)
def test_native_probe_timeout_is_capped_to_the_remaining_solve_budget(
    monkeypatch, method, args
):
    solver, _, _, calls = window_probe(monkeypatch)
    assert getattr(solver, method)(*args)
    assert len(calls) == 1
    assert calls[0][1]["timeout"] == pytest.approx(2.0)


@pytest.mark.parametrize("method,args", (*OPERATIONS, ("_focus_linux_window", ())))
@pytest.mark.parametrize("stop", ["deadline", "event"])
def test_stopped_native_probe_starts_no_command(monkeypatch, method, args, stop):
    solver, now, event, calls = window_probe(monkeypatch)
    if stop == "deadline":
        now[0] = 102.0
    else:
        event.set()
    with pytest.raises(SolveStopped):
        getattr(solver, method)(*args)
    assert calls == []


@pytest.mark.parametrize("method,args", (*OPERATIONS, ("_focus_linux_window", ())))
@pytest.mark.parametrize("stop", ["deadline", "event"])
def test_late_native_result_is_not_accepted_as_focus_or_geometry_proof(
    monkeypatch, method, args, stop
):
    def finish_late(now, event, *_):
        if stop == "deadline":
            now[0] = 102.1
        else:
            event.set()

    solver, _, _, calls = window_probe(monkeypatch, after_run=finish_late)
    with pytest.raises(SolveStopped):
        getattr(solver, method)(*args)
    assert len(calls) == 1
    assert solver.last_failure_reason == (
        "deadline_exceeded" if stop == "deadline" else "cancelled"
    )


def test_each_focus_fallback_uses_the_remaining_not_the_original_budget(monkeypatch):
    def advance(now, _event, *_):
        now[0] += 0.25

    solver, _, _, calls = window_probe(monkeypatch, after_run=advance)
    solver._linux_window_has_focus = lambda _: False
    assert solver._activate_linux_window_id("42") is False
    assert [command[1] for command, _ in calls] == [
        "windowactivate",
        "windowraise",
        "windowfocus",
    ]
    assert [options["timeout"] for _, options in calls] == [2.0, 1.75, 1.5]


def test_timeout_consuming_the_budget_cannot_start_focus_fallbacks(monkeypatch):
    def time_out(now, _event, command, kwargs):
        now[0] += kwargs["timeout"]
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    solver, now, _, calls = window_probe(monkeypatch, after_run=time_out)
    with pytest.raises(SolveStopped):
        solver._activate_linux_window_id("42")
    assert len(calls) == 1
    assert now[0] == pytest.approx(102.0)


def test_focus_settle_wait_is_interruptible_and_starts_no_final_probe(monkeypatch):
    solver, _, event, calls = window_probe(monkeypatch)
    waits = []

    def wait(seconds):
        waits.append(seconds)
        event.set()
        raise SolveStopped("cancelled")

    solver._wait_interruptibly = wait
    monkeypatch.setattr(
        captcha_os_windows.time,
        "sleep",
        lambda _: pytest.fail("native focus must not use an uninterruptible sleep"),
    )
    with pytest.raises(SolveStopped, match="cancelled"):
        solver._focus_linux_window()
    assert waits == [0.35]
    assert [command[1] for command, _ in calls] == [
        "search",
        "search",
        "search",
        "getwindowfocus",
    ]


@pytest.mark.parametrize("method,args", OPERATIONS)
def test_native_probe_without_a_solve_budget_keeps_the_existing_timeout(
    monkeypatch, method, args
):
    solver, _, _, calls = window_probe(monkeypatch, budgeted=False)
    assert getattr(solver, method)(*args)
    assert calls[0][1]["timeout"] == 3


def test_geometry_keeps_the_c_locale_for_parsing(monkeypatch):
    solver, _, _, calls = window_probe(monkeypatch)
    assert solver._linux_window_geometry() == {
        "x": 100.0,
        "y": 200.0,
        "width": 800.0,
        "height": 600.0,
    }
    assert calls[0][1]["env"]["LC_ALL"] == "C"
