"""Manual handoff ends input ownership, without changing pause or retry budgets."""

from copy import deepcopy

import pytest

from tools.pc2_solver_manual_handoff import (
    ManualChallengeRequired,
    attempt_or_manual_handoff,
    reconcile_completed_manual_handoff,
    retry_terminal_manual_report,
)


def state_and_status():
    return (
        {
            "challenge_id": "challenge-a",
            "scope": "seed",
            "slider_attempt_started_at": 100.0,
            "manual_pushed": True,
            "auth_complete_pending": False,
            "collection_resume_pending": False,
            "terminal_manual_pending": False,
            "slider_attempts": 5,
            "consecutive_failures": 5,
            "solver_cooldown_until": 900,
            "solver_cooldown_cycles": 2,
            "opaque_extension": {"preserved": True},
        },
        {
            "challenge_id": "challenge-a",
            "scope": "seed",
            "manual_required": True,
            "running": False,
            "paused": True,
        },
    )


def test_completed_receipt_clears_only_input_marker():
    state, status = state_and_status()
    expected = deepcopy(state)
    expected["slider_attempt_started_at"] = None
    saved = []
    assert reconcile_completed_manual_handoff(
        state, status, lambda s: saved.append(deepcopy(s))
    )
    assert state == expected and saved == [expected]
    assert status["paused"] and status["manual_required"]
    assert not reconcile_completed_manual_handoff(state, status, saved.append)
    assert len(saved) == 1


@pytest.mark.parametrize(
    ("where", "key", "value"),
    [
        ("state", "manual_pushed", False),
        ("state", "auth_complete_pending", True),
        ("state", "collection_resume_pending", True),
        ("state", "terminal_manual_pending", True),
        ("state", "scope", None),
        ("status", "challenge_id", "challenge-b"),
        ("status", "scope", "detail"),
        ("status", "running", True),
        ("status", "manual_required", False),
    ],
)
def test_unconfirmed_or_pending_handoff_is_not_reconciled(where, key, value):
    state, status = state_and_status()
    (state if where == "state" else status)[key] = value
    expected = deepcopy(state)
    assert not reconcile_completed_manual_handoff(
        state, status, lambda _: pytest.fail("unexpected save")
    )
    assert state == expected


def test_terminal_report_path_reconciles_without_replaying_report():
    state, status = state_and_status()
    assert (
        retry_terminal_manual_report(
            state,
            status,
            lambda: pytest.fail("must not replay manual report"),
            lambda _: None,
        )
        is False
    )
    assert state["slider_attempt_started_at"] is None
    assert state["slider_attempts"] == 5


def test_marker_is_cleared_before_fallible_manual_report():
    state, status = state_and_status()
    status["manual_required"] = False
    saved = []

    def attempt():
        raise ManualChallengeRequired

    def report():
        assert saved and saved[0]["slider_attempt_started_at"] is None
        raise OSError("report unavailable")

    with pytest.raises(OSError, match="report unavailable"):
        attempt_or_manual_handoff(
            attempt, state, status, report, lambda s: saved.append(deepcopy(s))
        )
    assert state["terminal_manual_pending"] is True
    assert state["slider_attempts"] == 5
