"""The real listener distinguishes backend completion from trusted page input."""

import json
from unittest.mock import Mock

import pytest

import tools.test.test_captcha_dom_evaluation as dom
from src.captcha_budget import SolveStopped
from src.captcha_dom import SLIDER_SELECTORS, TRACK_SELECTORS, eval_in_all_frames
from src.captcha_slider_geometry import geometry_expression
from tools import pc2_solver_diagnostics as diagnostics
from tools.test.test_captcha_os_target import make_probe, snapshot
from tools.test.test_captcha_slider_binding import installation
from tools.test.test_captcha_track_association import component

RECEIPT = {
    "press_seen": True,
    "press_on_target": True,
    "pressed_moves": 2,
    "release_seen": True,
    "document_current": True,
}


def run_receipt(monkeypatch, actions, *, frame=False):
    fixture = (
        dom.NODE_FIXTURE.replace(
            "const nodes = (spec.nodes || []).map(element);",
            "const nodes = (spec.nodes || []).map(element), listeners = new Map();",
        )
        .replace(
            "node.matches = query => matches(node, query);",
            """node.contains = candidate => {
            for (let cur = candidate; cur; cur = cur.parentElement) if (cur === node) return true;
            return false;
        };
        node.matches = query => matches(node, query);""",
        )
        .replace(
            "addEventListener: () => {}, removeEventListener: () => {},",
            """addEventListener: (type, fn) => listeners.set(type, fn),
        removeEventListener: (type, fn) => { if (listeners.get(type) === fn) listeners.delete(type); },
        dispatch: (type, event) => { if (listeners.has(type)) listeners.get(type)(event); },
        listenerCount: () => listeners.size,""",
        )
        .replace("window: {}, URL,", "window: {}, URL, performance: {now: () => 10},")
    )
    monkeypatch.setattr(dom, "NODE_FIXTURE", fixture)
    document = {"nodes": component(1, 0, 300, 10)}
    if frame:
        document = {"frames": [{"document": document}]}
    find = eval_in_all_frames(
        geometry_expression(
            SLIDER_SELECTORS, TRACK_SELECTORS, binding_key="__test_anchor"
        )
    )
    expression = "(function(){var selected=(" + find + ");"
    expression += (
        "var retained=window.__test_anchor, installed=(" + installation() + ");"
    )
    expression += """
        var d=retained.doc, n=retained.node;
        function emit(type, extra) {d.dispatch(type, {isTrusted:true, button:0,
            buttons:0, target:n, clientX:25, clientY:15, ...extra});}
    """
    expression += actions
    expression += """
        var receipt=window.__test_probe.close();
        return {receipt:receipt, cleaned:!window.__test_probe, listeners:d.listenerCount()};
    })()"""
    return dom.DocumentSolver(document)._send_cdp(
        "Runtime.evaluate", {"expression": expression}
    )["result"]["value"]


@pytest.mark.parametrize("frame", [False, True])
def test_real_listener_retains_full_receipt_after_handle_disappears(monkeypatch, frame):
    result = run_receipt(
        monkeypatch,
        """emit('mousemove', {buttons:1});
        emit('mouseup');
        emit('mousedown', {target:{parentElement:n}, buttons:1});
        emit('mousemove', {buttons:1}); emit('mousemove', {buttons:1});
        emit('mouseup'); n.isConnected=false; n.hidden=true;""",
        frame=frame,
    )
    assert result == {"receipt": RECEIPT, "cleaned": True, "listeners": 0}


@pytest.mark.parametrize("extra", ["isTrusted:false", "button:2, buttons:2"])
def test_synthetic_or_other_button_events_are_not_a_left_drag(monkeypatch, extra):
    result = run_receipt(
        monkeypatch,
        f"emit('mousedown', {{{extra}}}); emit('mousemove', {{buttons:1, isTrusted:false}});"
        f"emit('mouseup', {{{extra}}});",
    )
    assert result["receipt"] == {
        **RECEIPT,
        "press_seen": False,
        "press_on_target": False,
        "pressed_moves": 0,
        "release_seen": False,
    }


def test_first_press_is_not_rewritten_by_a_later_target_press(monkeypatch):
    result = run_receipt(
        monkeypatch,
        """emit('mousedown', {target:{}, buttons:1}); emit('mousedown', {buttons:1});
        emit('mousemove', {buttons:0}); emit('mouseup'); emit('mousemove', {buttons:1});""",
    )
    assert result["receipt"] == {
        **RECEIPT,
        "press_on_target": False,
        "pressed_moves": 0,
    }


@pytest.mark.parametrize(
    "change",
    [
        "retained.frame.isConnected=false;",
        "Object.defineProperty(retained.frame,'contentDocument',{value:{}});",
    ],
)
def test_frame_replacement_is_not_reported_as_current_document(monkeypatch, change):
    result = run_receipt(monkeypatch, "emit('mousedown');" + change, frame=True)
    assert result["receipt"]["document_current"] is False
    assert result["receipt"]["press_seen"] is True
    assert result["listeners"] == 0


def test_move_counter_is_bounded_and_stops_after_release(monkeypatch):
    result = run_receipt(
        monkeypatch,
        """emit('mousedown', {buttons:1});
        for (var i=0;i<10003;i++) emit('mousemove', {buttons:1});
        emit('mouseup'); emit('mousemove', {buttons:1});""",
    )
    assert result["receipt"]["pressed_moves"] == 10000


def test_close_reuses_one_cleanup_command_and_only_emits_safe_fields(monkeypatch):
    probe, solver, calls, _ = make_probe(monkeypatch, [snapshot()])
    assert probe.open()
    before = len(calls)
    solver._send_cdp = Mock(
        return_value={"result": {"value": {**RECEIPT, "secret": "private-sentinel"}}}
    )
    probe.backend_completed = True
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        probe.close()
        probe.close()
    assert len(calls) == before
    solver._send_cdp.assert_called_once()
    assert solver._send_cdp.call_args.args[1]["expression"].endswith("?.close()")
    assert events == [
        {
            "kind": "local_solver_diagnostic",
            "phase": "input_receipt",
            "backend_completed": True,
            **RECEIPT,
        }
    ]
    assert "private-" not in json.dumps(events)


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {**RECEIPT, "pressed_moves": True},
        {**RECEIPT, "pressed_moves": 10001},
        {**RECEIPT, "press_seen": "True"},
    ],
)
def test_missing_or_invalid_receipt_is_unknown_not_a_failed_drag(monkeypatch, value):
    probe, solver, _, _ = make_probe(monkeypatch, [snapshot()])
    assert probe.open()
    solver.last_failure_reason = "unchanged"
    solver._send_cdp = Mock(return_value={"result": {"value": value}})
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        probe.close()
    assert events == [
        {
            "kind": "local_solver_diagnostic",
            "phase": "input_receipt_unavailable",
            "backend_completed": False,
        }
    ]
    assert solver.last_failure_reason == "unchanged" and not probe.installed


@pytest.mark.parametrize(
    "error", [RuntimeError("private-sentinel"), SolveStopped("cancelled")]
)
def test_cleanup_failure_never_changes_existing_stop_or_adds_a_command(
    monkeypatch, error
):
    probe, solver, _, _ = make_probe(monkeypatch, [snapshot()])
    assert probe.open()
    solver._send_cdp = Mock(side_effect=error)
    solver.last_failure_reason = "cancelled"
    probe.close()
    solver._send_cdp.assert_called_once()
    assert solver.last_failure_reason == "cancelled" and not probe.installed
