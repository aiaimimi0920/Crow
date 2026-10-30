"""Navigation telemetry preserves privacy, old logs, limits and failure gates."""

import json
import logging
from unittest.mock import Mock

import pytest

from src.captcha_navigation_receipt import NAVIGATION_ENUMS, safe_navigation_fields
from src.captcha_solver import CaptchaSolver
from src.captcha_target_diagnostics import log_target_binding
from tools import pc2_solver_diagnostics as diagnostics
from tools.solver_binding_evidence import BINDING_ENUMS
from tools.solver_observation_evidence import summarize
from tools.test.test_captcha_navigation_receipt import (
    CHALLENGE,
    TARGET,
    frame_tree,
    receipt_solver,
)
from tools.test.test_captcha_target_binding_diagnostics import event, project

MATCH = {
    "navigation_probe": "ok",
    "navigation_frame": "match",
    "navigation_loader": "match",
    "navigation_url": "match",
}


def attach_receipt(solver):
    template = receipt_solver()
    solver.target_id = template.target_id
    solver._opened_target_ids = template._opened_target_ids
    solver._navigation_receipt = template._navigation_receipt
    solver._send_cdp = Mock(return_value=frame_tree())


def test_source_and_readback_share_exact_navigation_enums():
    assert {
        key: set(BINDING_ENUMS[key]) for key in NAVIGATION_ENUMS
    } == NAVIGATION_ENUMS


def test_preflight_emits_fresh_document_comparison_without_changing_slider_result(
    monkeypatch,
):
    solver = receipt_solver()
    solver.connect_tab = Mock(return_value=True)
    solver._page_challenge_summary = Mock(
        return_value={
            "href": CHALLENGE,
            "hasSlider": True,
            "readyState": "complete",
        }
    )
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        result = solver._preflight_current_challenge()
    assert result["has_slider"] and not result["already_authenticated"]
    assert events == [
        {
            **event("preflight", "query_changed", "both_absent"),
            "st_param": "current_missing",
            "page": "current_missing",
            **MATCH,
        }
    ]
    solver._send_cdp.assert_called_once_with("Page.getFrameTree")


def test_real_post_drag_and_retry_preclick_emissions_do_not_bypass_binding(monkeypatch):
    from tools.test.test_captcha_nc_retry_uncertain import retry_click_probe
    from tools.test.test_captcha_solve_loading_transition import (
        FAILED,
        SLIDER,
        solve_probe,
    )

    solver, _, _, _ = solve_probe(
        monkeypatch,
        [
            {
                **FAILED,
                "href": CHALLENGE,
                "readyState": "complete",
            }
        ],
        sliders=[SLIDER],
    )
    solver.target_url = TARGET
    attach_receipt(solver)
    solver._wait_for_verification_success.return_value = False
    solver._reset_failed_nc_challenge = (
        CaptchaSolver._reset_failed_nc_challenge.__get__(solver)
    )
    retry_click_probe(solver)
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    rows = [row for row in events if row["phase"] == "target_binding"]
    assert [row["stage"] for row in rows] == ["post_drag", "retry_preclick"]
    assert all({key: row[key] for key in MATCH} == MATCH for row in rows)
    assert solver.last_failure_reason == "slider_not_found"
    solver._click_css_point.assert_not_called()
    solver._reload_page.assert_not_called()
    solver._do_drag.assert_called_once()
    assert solver._send_cdp.call_count == 2
    assert "PRIVATE" not in json.dumps(events)


def test_extended_binding_logs_remain_bounded_and_private(monkeypatch, caplog):
    logger = logging.getLogger("src.captcha_preflight")
    before = logger.level, logger.filters[:]
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with caplog.at_level(logging.INFO), diagnostics.solver_attempt_diagnostics():
        for _ in range(100):
            log_target_binding(
                logger,
                "preflight",
                {"href": CHALLENGE},
                TARGET,
                navigation={**MATCH, "url": TARGET, "loaderId": "PRIVATE_LOADER"},
            )
    assert len(events) == 64 and not caplog.messages
    assert (logger.level, logger.filters) == before
    report = summarize(
        [project(0, {"kind": "local_solver_start", "target_url": TARGET})]
        + [project(1, row) for row in events]
    )
    assert len(report["attempts"][0]["target_binding_events"]) == 64
    assert not report["attempts"][0]["verified"]
    assert "PRIVATE" not in json.dumps(events) + json.dumps(report)


@pytest.mark.parametrize("value", [None, [], {}, True, "PRIVATE_MARKER", 12])
def test_navigation_values_are_revalidated_before_persistence_and_reporting(value):
    row = {**event("preflight", "match", "equal"), **dict.fromkeys(MATCH, value)}
    safe = project(1, row)
    assert all(safe[key] == "unknown" for key in MATCH)
    report = summarize(
        [
            project(0, {"kind": "local_solver_start", "target_url": TARGET}),
            {**row, "at": safe["at"], "container_id": "fixture"},
        ]
    )
    observed = report["attempts"][0]["target_binding_events"][0]
    assert all(observed[key] == "unknown" for key in MATCH)
    assert "PRIVATE" not in json.dumps(report)
    assert set(safe_navigation_fields(dict.fromkeys(MATCH, value)).values()) == {
        "unknown"
    }


def test_old_logs_remain_compatible_and_raw_navigation_suffix_is_rejected():
    old = (
        "[SOLVER] Target binding: stage=preflight binding=match "
        "location_code=equal st_param=equal auction_start_seg=equal page=equal"
    )
    assert diagnostics.diagnostic_event(old) == event("preflight", "match", "equal")
    suffix = " ".join(f"{key}={value}" for key, value in MATCH.items())
    assert diagnostics.diagnostic_event(old + " " + suffix) == {
        **event("preflight", "match", "equal"),
        **MATCH,
    }
    for extra in (" " + TARGET, "\nPRIVATE", " PRIVATE_FRAME", " loaderId=PRIVATE"):
        assert diagnostics.diagnostic_event(old + " " + suffix + extra) is None
