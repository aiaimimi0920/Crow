"""Fresh DOM anchor and independent pointer-event evidence precede every click."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src import captcha_os_target

OLD = {
    "x": 80,
    "y": 35,
    "width": 40,
    "height": 30,
    "selector": "#handle",
    "context": "main",
}
NEW = {"x": 200, "y": 150, "width": 40, "height": 30}


def snapshot(event=None):
    return {
        "rect": dict(NEW),
        "scale": 1,
        "focused": True,
        "visible": True,
        "event": event,
    }


def pointer_event(x=220, y=165, serial=1, hit=True, buttons=0, age=0):
    return {
        "x": x,
        "y": y,
        "serial": serial,
        "hit": hit,
        "buttons": buttons,
        "age": age,
    }


def make_probe(monkeypatch, samples):
    monkeypatch.setattr(captcha_os_target, "os", SimpleNamespace(name="posix"))
    calls, moves = [], []
    xy = [236, 197]
    samples = iter(samples)

    def evaluate(method, params):
        assert method == "Runtime.evaluate"
        calls.append(params["expression"])
        value = None if "?.close()" in params["expression"] else next(samples)
        return {"result": {"value": deepcopy(value)}}

    def move(_pointer, x, y, duration):
        xy[:] = [x, y]
        moves.append((x, y, duration))

    solver = SimpleNamespace(
        _send_cdp=evaluate,
        last_failure_reason=None,
        _linux_window_id="123",
        _linux_window_has_focus=lambda _wid: True,
        _wait_interruptibly=lambda _delay: None,
        _get_os_cursor_position=lambda _pointer: tuple(xy),
        _move_os_cursor_bounded=move,
    )
    probe = captcha_os_target.OSPointerTarget(solver, OLD, 100, 50)
    return probe, solver, calls, moves


def test_focus_reflow_uses_new_anchor_not_stale_input(monkeypatch):
    probe, _solver, calls, _moves = make_probe(monkeypatch, [snapshot()])
    assert probe.open()
    assert probe.rect == NEW
    assert probe.point == (220, 165)
    probe.close()
    assert "mousemove" in calls[0] and "event.isTrusted" in calls[0]
    assert "30000" in calls[0]
    assert calls[-1].endswith("?.close()")


def test_browser_event_corrects_native_mapping_before_press(monkeypatch):
    probe, solver, _calls, moves = make_probe(
        monkeypatch,
        [
            snapshot(),
            snapshot(pointer_event(220, 181, hit=False)),
            snapshot(pointer_event(serial=2)),
        ],
    )
    assert probe.open()
    assert probe.verify(None, {"x": 236, "y": 197}) == (236, 181)
    assert moves == [(236, 181, 0.15)]
    assert solver.last_failure_reason is None


@pytest.mark.parametrize(
    "mode",
    [
        "missing",
        "overlay",
        "button",
        "stale",
        "reflow",
        "focus",
        "hidden",
        "large",
        "nan",
        "expired",
    ],
)
def test_uncertain_or_changed_target_never_permits_press(monkeypatch, mode):
    sample = snapshot(pointer_event())
    if mode == "missing":
        sample["event"] = None
    if mode == "overlay":
        sample["event"]["hit"] = False
    if mode == "button":
        sample["event"]["buttons"] = 1
    if mode == "stale":
        sample["event"]["serial"] = 0
    if mode == "reflow":
        sample["rect"]["y"] += 20
    if mode == "hidden":
        sample["visible"] = False
    if mode == "large":
        sample["event"]["x"] += 100
    if mode == "nan":
        sample["event"]["y"] = float("nan")
    if mode == "expired":
        sample["event"]["age"] = 2000
    probe, solver, _calls, moves = make_probe(monkeypatch, [snapshot(), sample])
    assert probe.open()
    if mode == "focus":
        solver._linux_window_has_focus = lambda _wid: False
    assert probe.verify(None, {"x": 236, "y": 197}) is None
    assert solver.last_failure_reason.startswith("screen_mapping_")
    assert moves == []


def test_corrective_move_requires_new_trusted_event(monkeypatch):
    event = snapshot(pointer_event(220, 181, hit=False))
    probe, solver, _calls, moves = make_probe(monkeypatch, [snapshot(), event, event])
    assert probe.open()
    assert probe.verify(None, {"x": 236, "y": 197}) is None
    assert solver.last_failure_reason == "screen_mapping_pointer_unobserved"
    assert len(moves) == 1


def test_lost_install_ack_still_removes_probe(monkeypatch):
    probe, solver, calls, _moves = make_probe(monkeypatch, [None])
    assert not probe.open()
    probe.close()
    assert solver.last_failure_reason == "screen_mapping_target_unavailable"
    assert calls[-1].endswith("?.close()")


def test_pointer_moved_after_last_dom_event_blocks_press(monkeypatch):
    probe, solver, _calls, moves = make_probe(
        monkeypatch, [snapshot(), snapshot(pointer_event())]
    )
    assert probe.open()
    solver._get_os_cursor_position = lambda _pointer: (500, 500)
    assert probe.verify(None, {"x": 236, "y": 197}) is None
    assert solver.last_failure_reason == "screen_mapping_pointer_changed"
    assert moves == []


def test_visible_target_can_be_clicked_while_omnibox_owns_document_focus(monkeypatch):
    before, after = snapshot(), snapshot(pointer_event())
    before["focused"] = after["focused"] = False
    probe, solver, _calls, _moves = make_probe(monkeypatch, [before, after])
    assert probe.open()
    assert probe.verify(None, {"x": 236, "y": 197}) == (236, 197)
    assert solver.last_failure_reason is None
