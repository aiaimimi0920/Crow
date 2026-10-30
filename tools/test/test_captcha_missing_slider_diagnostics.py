"""Missing-slider evidence stays bounded, private and observational only."""

import json
import logging

import pytest

from tools import pc2_solver_diagnostics as diagnostics
from tools.solver_observation_evidence import project_line, summarize
from tools.test.test_captcha_solve_loading_transition import TARGET, solve_probe


def test_missing_slider_survives_the_real_log_filter_without_extra_io(monkeypatch):
    summary = {
        "href": TARGET,
        "readyState": "complete",
        "challengePresent": True,
        "probeFailed": False,
        "loginRequired": False,
        "hardBlock": False,
        "explicitFailure": False,
        "authenticatedPage": False,
        "bodyText": "private-body-marker",
        "title": "private-title-marker",
    }
    solver, _, reads, _ = solve_probe(monkeypatch, [summary])
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        assert solver.solve(max_attempts=1, slider_find_max_retries=1) is False
    assert solver.last_failure_reason == "max_attempts_exceeded"
    assert reads[0] == 1
    solver._find_slider.assert_called_once_with(max_retries=1, retry_delay=0)
    solver._reload_page.assert_called_once_with()
    solver._do_drag.assert_not_called()
    solver._send_cdp.assert_not_called()
    assert events == [
        {
            "kind": "local_solver_diagnostic",
            "phase": "slider_missing",
            "ready_state": "complete",
            "probe_failed": False,
            "target_ready": True,
            "challenge_present": True,
            "login_required": False,
            "hard_block": False,
            "explicit_failure": False,
            "authenticated_page": False,
        }
    ]
    assert "private-" not in json.dumps(events)


@pytest.mark.parametrize("ready", ["loading", "interactive", "complete", "secret"])
@pytest.mark.parametrize("foreign", [False, True])
def test_existing_summary_is_sanitized_without_changing_failure(
    monkeypatch, ready, foreign
):
    summary = {
        "href": TARGET.replace("123", "456") if foreign else TARGET,
        "readyState": ready,
        "probeFailed": True,
        "loginRequired": True,
        "hardBlock": True,
        "explicitFailure": True,
        "authenticatedPage": False,
    }
    solver, _, reads, _ = solve_probe(monkeypatch, [summary])
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == "cdp_unavailable" and reads[0] == 1
    event = next(e for e in events if e["phase"] == "slider_missing")
    assert event["ready_state"] == (ready if ready != "secret" else "unknown")
    assert event["target_ready"] is (
        not foreign and ready in {"interactive", "complete"}
    )
    assert event["probe_failed"] and event["login_required"] and event["hard_block"]
    assert event["explicit_failure"] and not event["authenticated_page"]
    solver._do_drag.assert_not_called()
    solver._send_cdp.assert_not_called()
    assert "secret" not in json.dumps(events)


def test_projection_keeps_only_strict_typed_missing_slider_evidence():
    event = {
        "kind": "local_solver_diagnostic",
        "phase": "slider_missing",
        "ready_state": "complete",
        "target_ready": False,
        "probe_failed": True,
        "challenge_present": True,
        "authenticated_page": False,
        "login_required": "secret",
        "hard_block": 1,
        "explicit_failure": None,
        "url": "private-url-marker",
        "bodyText": "private-body-marker",
    }
    projected = project_line("2026-10-27T08:00:00Z " + json.dumps(event), "fixture")
    assert projected["phase"] == "slider_missing"
    for key in (
        "ready_state",
        "target_ready",
        "probe_failed",
        "challenge_present",
        "authenticated_page",
    ):
        assert projected[key] == event[key]
    for key in ("login_required", "hard_block", "explicit_failure", "url", "bodyText"):
        assert key not in projected
    assert "private-" not in json.dumps(projected)


@pytest.mark.parametrize("ready", [None, [], {}, "private-marker", 17])
def test_projection_rejects_untrusted_ready_state(ready):
    event = {
        "kind": "local_solver_diagnostic",
        "phase": "slider_missing",
        "ready_state": ready,
    }
    assert (
        project_line("2026-10-27T08:00:00Z " + json.dumps(event), "fixture")[
            "ready_state"
        ]
        == "unknown"
    )


def test_missing_slider_telemetry_failure_does_not_change_cleanup(monkeypatch):
    solver, _, reads, _ = solve_probe(
        monkeypatch, [{"readyState": "complete", "href": TARGET}]
    )
    monkeypatch.setattr(
        diagnostics,
        "log_event",
        lambda _event: (_ for _ in ()).throw(OSError("private-marker")),
    )
    with diagnostics.solver_attempt_diagnostics():
        assert solver.solve(max_attempts=1) is False
    assert reads[0] == 1 and solver.last_failure_reason == "max_attempts_exceeded"
    assert not solver.lock.locked() and solver._solve_budget is None


def test_missing_slider_events_keep_the_existing_per_phase_cap(monkeypatch):
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    message = (
        "[SOLVER] Slider unavailable: ready=complete probeFailed=False targetReady=True "
        "challengePresent=False loginRequired=False hardBlock=False explicitFailure=False authenticatedPage=False"
    )
    with diagnostics.solver_attempt_diagnostics():
        for _ in range(100):
            logging.getLogger("src.captcha_orchestration").info(message)
    assert len(events) == 64


@pytest.mark.parametrize(
    "field,value", [("ready", "private-marker"), ("probeFailed", "true")]
)
def test_malformed_missing_slider_messages_are_not_published(field, value):
    message = (
        "[SOLVER] Slider unavailable: ready=complete probeFailed=False targetReady=True "
        "challengePresent=False loginRequired=False hardBlock=False explicitFailure=False authenticatedPage=False"
    )
    message = message.replace(
        field + "=" + ("complete" if field == "ready" else "False"), field + "=" + value
    )
    assert diagnostics.diagnostic_event(message) is None


def test_missing_slider_page_flags_are_not_automatic_success_evidence():
    rows = [
        {"kind": "local_solver_start", "target_url": TARGET},
        {
            "kind": "local_solver_diagnostic",
            "phase": "slider_missing",
            "authenticated_page": True,
        },
        {"kind": "local_solver_end", "success": True},
    ]
    events = [
        project_line(f"2026-10-27T08:00:0{i}Z " + json.dumps(row), "fixture")
        for i, row in enumerate(rows)
    ]
    counts = summarize(events)["counts"]
    assert counts["local_success"] == 1
    assert counts["automatic_local_success"] == counts["auth_confirmed"] == 0


def test_incomplete_summary_preserves_unknown_boolean_evidence(monkeypatch):
    solver, _, _, _ = solve_probe(monkeypatch, [{"probeFailed": True}])
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        assert solver.solve(max_attempts=1) is False
    event = events[0]
    assert event["probe_failed"] is True and event["ready_state"] == "unknown"
    assert event["challenge_present"] is event["authenticated_page"] is None
    projected = project_line("2026-10-27T08:00:00Z " + json.dumps(event), "fixture")
    assert (
        "challenge_present" not in projected and "authenticated_page" not in projected
    )
