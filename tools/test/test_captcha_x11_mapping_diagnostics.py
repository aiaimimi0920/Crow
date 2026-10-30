"""Rejected native mapping reports a fixed check, not private browser metadata."""

import logging
from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveStopped
from tools.test.test_captcha_x11_window_geometry import make_solver

METRICS = {
    "innerWidth": 1439,
    "innerHeight": 812,
    "outerWidth": 1439,
    "outerHeight": 899,
    "dpr": 1,
    "title": "private-browser-title-and-credential",
}
BOUNDS = {"left": -1, "top": -24, "width": 1439, "height": 899}
GEOMETRY = {"x": 0, "y": -23, "width": 1439, "height": 899}


def mapping_probe(monkeypatch):
    solver = make_solver(monkeypatch)
    solver._target_activation_verified = True
    solver._linux_window_geometry = Mock(return_value=GEOMETRY.copy())
    solver._linux_window_frame_extents = Mock(return_value={"bottom": 4})
    solver._window_metrics = Mock(return_value=METRICS.copy())
    solver._browser_window_bounds = Mock(return_value=BOUNDS.copy())
    solver._send_cdp = Mock(side_effect=AssertionError("No extra CDP I/O"))
    solver._focus_os_window = Mock(side_effect=AssertionError("No focus changes"))
    return solver


@pytest.mark.parametrize(
    ("change", "check"),
    [
        ("activation", "activation_unverified"),
        ("native", "native_geometry_unavailable"),
        ("metrics", "cdp_geometry_unavailable"),
        ("bounds", "cdp_geometry_unavailable"),
        ("number", "geometry_invalid"),
        ("empty", "geometry_invalid"),
        ("position", "geometry_mismatch"),
        ("size", "geometry_mismatch"),
        ("scale", "nonuniform_scale"),
    ],
)
def test_rejected_mapping_emits_only_a_fixed_reason(monkeypatch, caplog, change, check):
    solver = mapping_probe(monkeypatch)
    if change == "activation":
        solver._target_activation_verified = False
    elif change == "native":
        solver._linux_window_geometry.return_value = None
    elif change == "metrics":
        solver._window_metrics.return_value = None
    elif change == "bounds":
        solver._browser_window_bounds.return_value = None
    elif change == "number":
        solver._window_metrics.return_value["dpr"] = "private-invalid-number"
    elif change == "empty":
        solver._window_metrics.return_value["outerWidth"] = 0
    elif change == "position":
        solver._browser_window_bounds.return_value["left"] = 500
    elif change == "size":
        solver._browser_window_bounds.return_value["height"] = 1000
    else:
        solver._window_metrics.return_value["outerHeight"] = 812

    with caplog.at_level(logging.WARNING):
        assert solver._css_to_x11_window_screen(592.5, 506, 256) is None

    messages = [r.getMessage() for r in caplog.records]
    assert f"[SOLVER] X11 screen mapping unavailable check={check}" in messages
    assert "private" not in caplog.text
    assert solver.last_failure_reason is None
    solver._send_cdp.assert_not_called()
    solver._focus_os_window.assert_not_called()


def test_verified_mapping_has_no_failure_diagnostic_or_new_io(monkeypatch, caplog):
    solver = mapping_probe(monkeypatch)
    with caplog.at_level(logging.WARNING):
        mapped = solver._css_to_x11_window_screen(592.5, 506, 256)
    assert mapped["x"] == 592.5 and mapped["y"] == 566
    assert mapped["distance"] == 256
    assert not caplog.records
    for method in (
        solver._linux_window_geometry,
        solver._linux_window_frame_extents,
        solver._window_metrics,
        solver._browser_window_bounds,
    ):
        method.assert_called_once_with()
    solver._send_cdp.assert_not_called()
    solver._focus_os_window.assert_not_called()


def test_native_rejection_still_allows_original_verified_screenshot_fallback(
    monkeypatch,
):
    solver = mapping_probe(monkeypatch)
    solver._window_metrics.return_value["outerHeight"] = 812
    solver._css_to_client_screen = Mock(
        return_value={"x": 592.5, "y": 566, "distance": 256, "source": "dpr_fallback"}
    )
    solver._css_to_cdp_window_screen = Mock(return_value=None)
    solver._viewport_origin_on_screen = Mock(
        return_value={
            "left": 0,
            "top": 60,
            "width": 1439,
            "height": 812,
            "clipped": False,
        }
    )
    mapped = solver._map_css_to_screen(
        592.5, 506, 256, slider_info={"width": 42, "height": 30}
    )
    assert mapped["source"] == "screenshot_viewport" and mapped["located"] is True
    assert mapped["x"] == 592.5 and mapped["y"] == 566
    assert mapped["distance"] == 256 and solver.last_failure_reason is None
    solver._viewport_origin_on_screen.assert_called_once()


def test_fixed_mapping_warning_reaches_existing_attempt_logging(monkeypatch, caplog):
    from tools.pc2_solver_diagnostics import solver_attempt_diagnostics

    solver = mapping_probe(monkeypatch)
    solver._target_activation_verified = False
    with caplog.at_level(logging.WARNING), solver_attempt_diagnostics():
        assert solver._css_to_x11_window_screen(592.5, 506, 256) is None
    assert len(caplog.records) == 1
    assert caplog.records[0].getMessage() == (
        "[SOLVER] X11 screen mapping unavailable check=activation_unverified"
    )


@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
@pytest.mark.parametrize(
    "method",
    [
        "_linux_window_geometry",
        "_linux_window_frame_extents",
        "_window_metrics",
        "_browser_window_bounds",
    ],
)
def test_mapping_diagnostic_cannot_swallow_a_solve_stop(
    monkeypatch, caplog, reason, method
):
    solver = mapping_probe(monkeypatch)
    getattr(solver, method).side_effect = SolveStopped(reason)
    with pytest.raises(SolveStopped, match=reason):
        solver._css_to_x11_window_screen(592.5, 506, 256)
    assert not caplog.records


def test_windows_skips_linux_diagnostics_and_all_native_queries(monkeypatch, caplog):
    from tools.test.captcha_solver_test_context import set_solver_platform

    solver = mapping_probe(monkeypatch)
    set_solver_platform(monkeypatch, "nt")
    assert solver._css_to_x11_window_screen(592.5, 506, 256) is None
    assert not caplog.records
    solver._linux_window_geometry.assert_not_called()
