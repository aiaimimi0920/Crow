"""Preserve the exact failed pre-input boundary without relaxing any guard."""

import json

import pytest

from tools import pc2_solver_diagnostics as diagnostics
from tools.solver_observation_evidence import project_line, summarize
from tools.test.test_captcha_dom_evaluation import DocumentSolver
from tools.test.test_captcha_os_target import make_probe, snapshot
from tools.test.test_captcha_slider_binding import installation, run_binding
from tools.test.test_captcha_track_association import component


def project(second, **event):
    return project_line(
        f"2026-10-29T00:00:{second:02d}Z " + json.dumps(event), "fixture"
    )


@pytest.mark.parametrize(
    ("sample", "focused", "bound", "check"),
    [
        (None, False, False, "open_native_focus"),
        (None, True, False, "open_snapshot"),
        (snapshot(), True, True, "open_binding"),
        ({"probe_failure": "binding_expired"}, True, True, "binding_expired"),
        ({"probe_failure": "private-sentinel"}, True, True, "open_snapshot"),
    ],
)
def test_actual_open_failure_reaches_safe_observer(
    monkeypatch, sample, focused, bound, check
):
    probe, solver, calls, moves = make_probe(monkeypatch, [sample])
    solver._linux_window_has_focus = lambda _wid: focused
    if bound:
        probe.info = {**probe.info, "binding_key": "private-binding-key"}
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        assert not probe.open()
    assert events == [
        {
            "kind": "local_solver_diagnostic",
            "phase": "pointer_failure",
            "reason": "target_unavailable",
            "check": check,
        }
    ]
    assert not moves
    assert bool(calls) is focused
    assert solver.last_failure_reason == "screen_mapping_target_unavailable"
    row = project(1, **events[0], secret="private-sentinel")
    assert row["check"] == check
    assert "private-" not in json.dumps(row)
    probe.close()
    assert calls[-1].endswith("?.close()")


@pytest.mark.parametrize(
    ("mutation", "check"),
    [
        ("delete window.__test_anchor;", "binding_missing"),
        ("window.__test_anchor.expiresAt=0;", "binding_expired"),
        ("window.__test_anchor.node.ownerDocument={};", "binding_document"),
        ("window.__test_anchor.node.parentElement=null;", "binding_changed"),
        ("window.__test_anchor.node.isConnected=false;", "node_unavailable"),
        ("window.__test_anchor.track.hidden=true;", "track_unavailable"),
        (
            "Object.defineProperty(window.__test_anchor.frame,'contentDocument',{value:{}});",
            "frame_unavailable",
        ),
    ],
)
def test_real_bound_javascript_preserves_exact_failure_without_selector_fallback(
    monkeypatch, mutation, check
):
    result = run_binding(
        {"frames": [{"document": {"nodes": component(1, 0, 400, 20)}}]},
        mutation,
    )
    assert result["snapshot"] == {"probe_failure": check}
    probe, solver, _calls, moves = make_probe(monkeypatch, [result["snapshot"]])
    probe.info = {**probe.info, "binding_key": "private-binding-key"}
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        assert not probe.open()
    assert events[0]["check"] == check
    assert solver.last_failure_reason == "screen_mapping_target_unavailable"
    assert not moves
    probe.close()


@pytest.mark.parametrize(
    ("phase", "fields"),
    [
        ("slider_geometry", {}),
        ("drag_distance", {"distance": 256.0, "track_width": 300, "slider_width": 42}),
        ("pointer_failure", {"reason": "target_unavailable", "check": "open_snapshot"}),
        ("pointer_hit", {"delta": 0.5, "corrections": 1}),
        ("cursor_position", {"delta": 0.5}),
    ],
)
def test_projector_retains_bounded_existing_pointer_evidence(phase, fields):
    row = project(
        1,
        kind="local_solver_diagnostic",
        phase=phase,
        **fields,
        secret="private-sentinel",
        css_x=123,
        expected_x=456,
    )
    assert row is not None
    assert row["phase"] == phase
    assert all(row[key] == value for key, value in fields.items())
    assert "private-" not in json.dumps(row)
    assert not {"css_x", "expected_x"}.intersection(row)


@pytest.mark.parametrize("bad", [True, "1", -1, 10001, float("nan"), float("inf")])
def test_pointer_projection_drops_invalid_numbers_and_unknown_enum(bad):
    row = project(
        1,
        kind="local_solver_diagnostic",
        phase="pointer_failure",
        reason="private-sentinel",
        check="private-sentinel",
        delta=bad,
        corrections=bad,
    )
    assert row is not None
    assert row["reason"] == row["check"] == "unknown"
    assert "delta" not in row and "corrections" not in row
    assert "private-" not in json.dumps(row)


def test_summary_links_only_current_bounded_evidence_and_never_claims_success():
    start = project(
        0, kind="local_solver_start", target_url="https://sf-item.taobao.com/"
    )
    geometry = project(1, kind="local_solver_diagnostic", phase="slider_geometry")
    failure = project(
        2,
        kind="local_solver_diagnostic",
        phase="pointer_failure",
        reason="target_unavailable",
        check="binding_expired",
    )
    end = project(
        3,
        kind="local_solver_end",
        success=False,
        failure_reason="execution_unavailable",
    )
    assert geometry is not None and failure is not None
    foreign = dict(failure, container_id="foreign")
    report = summarize([start, foreign, geometry] + [failure] * 100 + [end, failure])
    attempt = report["attempts"][0]
    assert attempt["failure_reason"] == "execution_unavailable"
    assert len(attempt["pointer_events"]) == 64
    assert attempt["pointer_events"][0] == {
        "at": geometry["at"],
        "phase": "slider_geometry",
    }
    assert attempt["pointer_events"][1]["check"] == "binding_expired"
    assert not attempt["drags"] and not attempt["verified"]
    assert report["counts"]["automatic_local_success"] == 0
    assert report["counts"]["auth_confirmed"] == 0


def test_legacy_unbound_lookup_still_skips_missing_node_in_earlier_frame():
    expression = installation().replace(
        'bindingKey = "__test_anchor"', "bindingKey = null"
    )
    document = {
        "frames": [
            {"document": {"nodes": []}},
            {"document": {"nodes": component(1, 0, 400, 20)}},
        ]
    }
    result = DocumentSolver(document)._send_cdp(
        "Runtime.evaluate", {"expression": expression}
    )["result"]["value"]
    assert result["visible"] is True
    assert result["geometry_bound"] is False
    assert "probe_failure" not in result
