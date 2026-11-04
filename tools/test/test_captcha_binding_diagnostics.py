"""Binding diagnostics explain denial without publishing identity or granting input."""

import json
import logging

import pytest

from src.captcha_challenge_binding import INPUT_BINDING_RESULTS
from tools.pc2_solver_diagnostics import diagnostic_event
from tools.solver_observation_evidence import project_line
from tools.test.navigation_flow_fixtures import CHALLENGE, NEXT, prepared, scripted


@pytest.mark.parametrize(
    "change,expected",
    [
        ("none", "accepted"),
        ("missing_geometry", "geometry_missing"),
        ("receipt", "receipt_unavailable"),
        ("inactive", "flow_inactive"),
        ("initial_loader", "flow_origin_mismatch"),
        ("missing_commit", "flow_transition_unconfirmed"),
        ("pending", "flow_not_terminal"),
    ],
)
def test_geometry_denial_has_a_fixed_reason_and_preserves_admission(
    caplog, change, expected
):
    events = scripted()
    if change == "initial_loader":
        first = events[0]["params"]
        first["loaderId"] = "PRIVATE_WRONG_LOADER"
    elif change == "missing_commit":
        events.pop(1)
    solver, _sock = prepared(events, loader=NEXT)
    if change == "receipt":
        solver._navigation_receipt = None
    elif change == "inactive":
        solver._navigation_trace.state = "unavailable"
    elif change == "pending":
        solver._navigation_trace.events.append(
            ("requested", solver.target_id, "script", "queryless_challenge")
        )
        # A pending request on the actual root frame must fail closed.
        solver._navigation_trace.events[-1] = (
            "requested",
            solver._navigation_receipt.frame_id,
            "script",
            "queryless_challenge",
        )
    original = solver._send_cdp

    def send(method, params=None):
        if method == "Runtime.evaluate":
            return {
                "result": {
                    "value": {
                        "found": change != "missing_geometry",
                        "href": CHALLENGE,
                        "hasSlider": True,
                        "readyState": "complete",
                        "binding_key": "PRIVATE_ANCHOR",
                    }
                }
            }
        return original(method, params)

    solver._send_cdp = send
    with caplog.at_level(logging.INFO, logger="src.captcha_slider"):
        geometry = solver._read_slider_geometry(binding_key="PRIVATE_ANCHOR")
    assert bool(geometry and geometry.get("_challenge_binding")) is (change == "none")
    messages = [
        r.getMessage()
        for r in caplog.records
        if "Slider input binding:" in r.getMessage()
    ]
    assert messages == [f"[SOLVER] Slider input binding: result={expected}"]
    assert "PRIVATE" not in " ".join(messages)


@pytest.mark.parametrize("reason", sorted(INPUT_BINDING_RESULTS))
def test_fixed_binding_reason_round_trips_through_runtime_and_observation(reason):
    event = diagnostic_event(f"[SOLVER] Slider input binding: result={reason}")
    assert event == {
        "kind": "local_solver_diagnostic",
        "phase": "input_binding",
        "binding_result": reason,
    }
    projected = project_line("2026-11-04T15:00:00Z " + json.dumps(event), "fixture")
    assert projected["binding_result"] == reason


@pytest.mark.parametrize(
    "reason",
    ["PRIVATE_SECRET", "https://fixture.invalid/PRIVATE", "flow_inactive PRIVATE"],
)
def test_untrusted_binding_diagnostic_cannot_publish_values(reason):
    event = diagnostic_event(f"[SOLVER] Slider input binding: result={reason}")
    assert event is None or event["binding_result"] == "unknown"
    projected = project_line(
        "2026-11-04T15:00:00Z "
        + json.dumps(
            {
                "kind": "local_solver_diagnostic",
                "phase": "input_binding",
                "binding_result": reason,
            }
        ),
        "fixture",
    )
    assert projected["binding_result"] == "unknown"
    assert "PRIVATE" not in json.dumps(projected)
