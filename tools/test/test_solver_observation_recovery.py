"""Authentication recovery is not the same evidence as verified slider success."""

import pytest

from tools.solver_observation_evidence import summarize
from tools.test.test_solver_observation import event, payload, success


def recovery(*, dragged=True, succeeded=True):
    rows = success()
    rows.pop(2)  # Recovery can succeed without the slider's verified diagnostic.
    if not dragged:
        rows.pop(1)
    end = next(row for row in rows if row["kind"] == "local_solver_end")
    end["success"] = succeeded
    return rows


def confirmation(*, confirmed=True, **changes):
    return event(
        "auth_complete_result",
        4,
        result={"confirmed": confirmed, "result": payload(**changes)},
    )


@pytest.mark.parametrize("dragged", [False, True])
@pytest.mark.parametrize("delayed", [False, True])
def test_recovery_ack_links_without_inventing_verified_drag(dragged, delayed):
    rows = recovery(dragged=dragged) + [confirmation(confirmed=not delayed)]
    if delayed:
        rows.append(event("auth_complete_confirmed", 5, result=payload()))
    report = summarize(rows)
    counts = report["counts"]
    assert counts["auth_confirmed"] == counts["bound_health_verified"] == 1
    assert counts["auth_confirmed_without_verified_drag"] == 1
    assert counts["automatic_local_success"] == 0
    assert counts["unlinked_auth_confirmations"] == 0
    assert report["attempts"][0]["verified"] is False


def test_verified_slider_ack_stays_separate_from_recovery_count():
    counts = summarize(success() + [confirmation()])["counts"]
    assert counts["automatic_local_success"] == counts["auth_confirmed"] == 1
    assert counts["auth_confirmed_without_verified_drag"] == 0


@pytest.mark.parametrize("succeeded", [False, True])
def test_unconfirmed_recovery_does_not_become_auth_success(succeeded):
    rows = recovery(succeeded=succeeded) + [confirmation(confirmed=False)]
    counts = summarize(rows)["counts"]
    assert counts["auth_confirmed"] == 0
    assert counts["auth_confirmed_without_verified_drag"] == 0


def test_failed_local_attempt_cannot_claim_later_auth_confirmation():
    counts = summarize(recovery(succeeded=False) + [confirmation()])["counts"]
    assert counts["auth_confirmed"] == 0
    assert counts["unlinked_auth_confirmations"] == 1


@pytest.mark.parametrize(
    "changes",
    [{"scope": "seed"}, {"source": "pc1_manual"}, {"auth_state_confirmed": False}],
)
def test_recovery_keeps_existing_scope_source_and_confirmation_checks(changes):
    counts = summarize(recovery() + [confirmation(**changes)])["counts"]
    assert counts["auth_confirmed"] == 0


@pytest.mark.parametrize("missing", ["challenge", "target", "request"])
def test_recovery_missing_binding_is_not_guessed(missing):
    rows = recovery()
    ack = confirmation()
    if missing == "challenge":
        rows.pop()
    elif missing == "target":
        rows[0]["target_hash"] = None
    else:
        ack["challenge_hash"] = ack["target_hash"] = None
    counts = summarize(rows + [ack])["counts"]
    assert counts["auth_confirmed"] == 0
    assert counts["unlinked_auth_confirmations"] == 1


def test_ambiguous_recovery_is_not_linked_by_time_proximity():
    rows = recovery() + recovery() + [confirmation()]
    counts = summarize(rows)["counts"]
    assert counts["auth_confirmed"] == 0
    assert counts["unlinked_auth_confirmations"] == 1


def test_recovery_delayed_ack_cannot_cross_container():
    rows = recovery() + [confirmation(confirmed=False)]
    ack = event("auth_complete_confirmed", 5, result=payload())
    ack["container_id"] = "container-b"
    assert summarize(rows + [ack])["counts"]["auth_confirmed"] == 0


def test_recovery_delayed_ack_keeps_original_attempt_after_new_start():
    rows = recovery() + [
        confirmation(confirmed=False),
        event("local_solver_start", 5),
        event("auth_complete_confirmed", 6, result=payload()),
    ]
    report = summarize(rows)
    assert report["attempts"][0]["auth_confirmed"] is True
    assert report["attempts"][1]["auth_confirmed"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("completion_id", "another"),
        ("challenge_id", "another"),
        ("target_url", "https://sf-item.taobao.com/another"),
        ("scope", "seed"),
    ],
)
def test_recovery_request_binding_is_not_relaxed(field, value):
    request = {
        "completion_id": "private-completion",
        "challenge_id": "challenge-a",
        "target_url": "https://sf-item.taobao.com/item?secret=private",
        "scope": "detail",
    }
    request[field] = value
    ack = event(
        "auth_complete_result",
        4,
        request=request,
        result={"confirmed": True, "result": payload(), "state": {}},
    )
    assert summarize(recovery() + [ack])["counts"]["auth_confirmed"] == 0


def test_later_recovery_ack_does_not_rewrite_failed_slider_diagnostics():
    rows = recovery()
    rows.insert(
        2, event("local_solver_diagnostic", 2, phase="verification", success=False)
    )
    rows.insert(
        3,
        event("local_solver_diagnostic", 2, phase="challenge_failure", code="none"),
    )
    rows += [confirmation(confirmed=False)]
    ack = event("auth_complete_confirmed", 5, result=payload())
    report = summarize(rows + [ack, ack])
    attempt = report["attempts"][0]
    assert attempt["last_challenge_failure"]["code"] == "none"
    assert attempt["auth_confirmation_seconds"] == 2
    assert report["counts"]["auth_confirmed_without_verified_drag"] == 1
    assert report["counts"]["automatic_local_success"] == 0
