"""ACK diagnostics stay passive, bound to identity and distinct from local success."""

import json

import pytest

from tools.solver_observation_evidence import project_line, summarize
from tools.test.test_solver_observation import event, payload, success


def pending(kind="auth_complete_result", second=4, **snapshot):
    body = payload(cookie_snapshot={"status": "running", **snapshot})
    result = (
        {"confirmed": False, "result": body} if kind == "auth_complete_result" else body
    )
    body["auth_state_confirmed"] = False
    return event(kind, second, result=result)


def test_pending_snapshot_failure_is_not_a_failed_local_solve_or_confirmed_auth():
    rows = success() + [
        pending(result={"reason": "cookie_snapshot_candidate_unhealthy"})
    ]
    report = summarize(rows)
    attempt = report["attempts"][0]
    assert attempt["automatic_local_success"] is True
    assert attempt["auth_confirmed"] is False
    assert attempt["last_pending_snapshot_status"] == "running"
    assert (
        attempt["last_pending_snapshot_reason"] == "cookie_snapshot_candidate_unhealthy"
    )
    assert "auth_confirmation_seconds" not in attempt
    assert report["counts"]["local_success_without_auth_confirmation"] == 1


def test_retry_pending_updates_only_the_matching_confirmation():
    retry = pending(
        "auth_complete_retry_pending",
        6,
        status="pending",
        reason="refresh_already_running",
    )
    assert retry is not None
    rows = success() + [pending(), retry]
    attempt = summarize(rows)["attempts"][0]
    assert attempt["last_pending_snapshot_status"] == "pending"
    assert attempt["last_pending_snapshot_reason"] == "refresh_already_running"


@pytest.mark.parametrize("different", ["completion_hash", "container_id", "scope"])
def test_unrelated_retry_does_not_replace_pending_reason(different):
    retry = pending("auth_complete_retry_pending", 6, status="failed")
    assert retry is not None
    retry[different] = "unrelated"
    rows = success() + [pending(reason="refresh_already_running"), retry]
    assert summarize(rows)["attempts"][0]["last_pending_snapshot_status"] == "running"


def test_first_confirmation_timestamp_and_latency_survive_duplicate_ack():
    rows = success() + [
        pending(),
        event("auth_complete_confirmed", 8, result=payload()),
        event("auth_complete_confirmed", 18, result=payload()),
    ]
    report = summarize(rows)
    attempt = report["attempts"][0]
    assert attempt["auth_confirmed_at"] == rows[-2]["at"]
    assert attempt["auth_confirmation_seconds"] == 5
    assert report["counts"]["auth_confirmed"] == 1
    assert report["counts"]["local_success_without_auth_confirmation"] == 0


def test_initial_ack_can_confirm_immediately():
    rows = success() + [
        event(
            "auth_complete_result", 4, result={"confirmed": True, "result": payload()}
        )
    ]
    assert summarize(rows)["attempts"][0]["auth_confirmation_seconds"] == 1


def test_late_pending_does_not_downgrade_a_confirmed_attempt():
    rows = success() + [
        pending(),
        event("auth_complete_confirmed", 8, result=payload()),
        pending("auth_complete_retry_pending", 18, status="failed"),
    ]
    attempt = summarize(rows)["attempts"][0]
    assert attempt["auth_confirmed"] is True
    assert attempt["last_pending_snapshot_status"] == "running"


def test_other_source_cannot_overwrite_pending_diagnostics():
    retry = pending("auth_complete_retry_pending", 6, status="failed")
    retry["automatic_source"] = False
    rows = success() + [pending(), retry]
    assert summarize(rows)["attempts"][0]["last_pending_snapshot_status"] == "running"


def test_negative_clock_delta_is_unknown_not_zero_or_negative_latency():
    rows = success() + [
        event(
            "auth_complete_result", 2, result={"confirmed": True, "result": payload()}
        )
    ]
    attempt = summarize(rows)["attempts"][0]
    assert attempt["auth_confirmed"] is True
    assert "auth_confirmation_seconds" not in attempt


@pytest.mark.parametrize(
    "reason", ["token=private", {"secret": "private"}, ["private"]]
)
def test_unknown_snapshot_metadata_never_retains_raw_values(reason):
    row = pending(status="secret=private", result={"reason": reason})
    assert row["snapshot_status"] == "unknown"
    assert row["snapshot_reason"] == "other"
    assert "private" not in json.dumps(row)


def test_projection_still_ignores_unrelated_events():
    assert (
        project_line('2026-10-26T10:00:00Z {"kind":"private_event"}', "container")
        is None
    )
