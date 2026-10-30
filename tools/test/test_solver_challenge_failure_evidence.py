"""Failure reports retain bounded diagnostics without changing solver outcomes."""

import json

import pytest

from tools.pc2_solver_diagnostics import diagnostic_event
from tools.solver_observation_evidence import project_line, summarize


def project(second=1, **values):
    event = {"kind": "local_solver_diagnostic", "phase": "challenge_failure", **values}
    return project_line(
        f"2026-10-28T02:10:{second:02d}Z " + json.dumps(event), "fixture"
    )


def lifecycle(*diagnostics):
    raw = [
        {"kind": "local_solver_start", "target_url": "https://sf-item.taobao.com/123"},
        *diagnostics,
        {
            "kind": "local_solver_end",
            "success": False,
            "failure_reason": "manual_required",
        },
    ]
    return [
        project_line(f"2026-10-28T02:10:{i:02d}Z " + json.dumps(row), "fixture")
        for i, row in enumerate(raw)
    ]


def test_real_failure_producer_survives_projection_and_report():
    diagnostic = diagnostic_event(
        "[SOLVER] Challenge diagnostic: code=error:300 title=private-title "
        "class=private-class path=private-path retryable=True"
    )
    assert diagnostic == {
        "kind": "local_solver_diagnostic",
        "phase": "challenge_failure",
        "code": "error:300",
        "retryable": True,
    }
    rows = lifecycle(diagnostic)
    assert rows[1]["code"] == "error:300"
    assert rows[1]["retryable"] is True
    report = summarize(rows)
    assert report["attempts"][0]["last_challenge_failure"] == {
        "at": "2026-10-28T02:10:01Z",
        "code": "error:300",
        "retryable": True,
    }
    assert report["counts"]["automatic_local_success"] == 0
    assert "private-" not in json.dumps(rows) + json.dumps(report)


@pytest.mark.parametrize("code", ["error:1", "error:123456", "none", "other"])
@pytest.mark.parametrize("retryable", [True, False])
def test_known_safe_diagnostics_remain_exact(code, retryable):
    row = project(code=code, retryable=retryable)
    assert row["code"] == code and row["retryable"] is retryable


@pytest.mark.parametrize(
    "code",
    ["private-token", "error:1234567", "error:１２３", "error:12\n", None, [], {}],
)
def test_unknown_failure_codes_cannot_leak_or_break_projection(code):
    row = project(code=code)
    assert row["code"] == "other"
    assert "private" not in json.dumps(row)


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_retryability_must_be_a_strict_boolean(value):
    assert "retryable" not in project(retryable=value)


def test_old_events_keep_unknown_fields_absent():
    row = project()
    assert "code" not in row and "retryable" not in row
    report = summarize(
        lifecycle({"kind": "local_solver_diagnostic", "phase": "challenge_failure"})
    )
    assert report["attempts"][0]["last_challenge_failure"] == {
        "at": "2026-10-28T02:10:01Z"
    }
    assert "last_challenge_failure" not in summarize(lifecycle())["attempts"][0]


def test_only_latest_failure_is_retained_and_completed_attempt_is_immutable():
    rows = lifecycle(
        {
            "kind": "local_solver_diagnostic",
            "phase": "challenge_failure",
            "code": "error:1",
        },
        {
            "kind": "local_solver_diagnostic",
            "phase": "challenge_failure",
            "code": "none",
            "retryable": False,
        },
    )
    rows.append(project(8, code="error:2", retryable=True))
    attempt = summarize(rows)["attempts"][0]
    assert attempt["last_challenge_failure"] == {
        "at": "2026-10-28T02:10:02Z",
        "code": "none",
        "retryable": False,
    }
    assert attempt["failure_reason"] == "manual_required"


def test_other_phase_and_container_cannot_supply_failure_diagnostics():
    assert "code" not in project(phase="verification", code="error:1", retryable=True)
    rows = lifecycle()
    foreign = project(code="error:1", retryable=True)
    foreign["container_id"] = "other"
    rows.insert(1, foreign)
    assert "last_challenge_failure" not in summarize(rows)["attempts"][0]


def test_observer_restart_boundary_cannot_attach_a_late_failure():
    rows = lifecycle()
    rows.insert(1, {"kind": "observer_restart_boundary"})
    rows.insert(2, project(code="error:1", retryable=True))
    attempt = summarize(rows)["attempts"][0]
    assert "last_challenge_failure" not in attempt
    assert attempt["completed"] is False


def test_report_revalidates_preexisting_event_files():
    rows = lifecycle()
    row = project()
    row.update(code="private-token", retryable="private-token")
    rows.insert(1, row)
    failure = summarize(rows)["attempts"][0]["last_challenge_failure"]
    assert failure == {"at": "2026-10-28T02:10:01Z", "code": "other"}
    assert "private" not in json.dumps(failure)
