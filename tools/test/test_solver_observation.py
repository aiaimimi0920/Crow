"""Synthetic observations: no live browser, Docker, network or credentials."""

import json

import pytest

from tools.solver_observation_evidence import project_line, summarize, timestamp


def event(kind, second=0, **values):
    if kind == "auth_complete_result" and isinstance(values.get("result"), dict):
        values["result"].setdefault(
            "state",
            {
                "challenge_id": "challenge-a",
                "auth_complete_target_url": "https://sf-item.taobao.com/item?secret=private",
            },
        )
    raw = json.dumps({"kind": kind, **values})
    return project_line(
        f"2026-10-06T12:00:{second:02d}.123456789Z {raw}", "container-a"
    )


def success():
    return [
        event(
            "local_solver_start",
            target_url="https://sf-item.taobao.com/item?secret=private",
        ),
        event(
            "local_solver_diagnostic",
            1,
            phase="os_drag",
            input="pyautogui",
            profile="fast_exact_v3",
            distance=256,
        ),
        event("local_solver_diagnostic", 2, phase="verified"),
        event("local_solver_end", 3, success=True),
        event(
            "auth_completion_challenge_resolved",
            3,
            completion_challenge_id="challenge-a",
        ),
    ]


def payload(**changes):
    result = {
        "completion_id": "private-completion",
        "scope": "detail",
        "source": "pc2_local_solver",
        "auth_state_confirmed": True,
        "cookie_snapshot": {
            "refreshed": True,
            "result": {
                "health": {"healthy": False, "scope": "detail", "scope_healthy": True}
            },
        },
    }
    result.update(changes)
    return result


def test_correlated_automatic_success():
    rows = success() + [
        event(
            "auth_complete_result", 4, result={"confirmed": False, "result": payload()}
        ),
        event("auth_complete_confirmed", 5, result=payload()),
    ]
    counts = summarize(rows)["counts"]
    assert (
        counts["automatic_local_success"]
        == counts["auth_confirmed"]
        == counts["bound_health_verified"]
        == 1
    )
    assert counts["unlinked_auth_confirmations"] == 0
    assert "private" not in json.dumps(rows)


@pytest.mark.parametrize("remove", [1, 2, 3])
def test_incomplete_proof_is_not_automatic_success(remove):
    rows = success()
    rows.pop(remove)
    assert summarize(rows)["counts"]["automatic_local_success"] == 0


def test_healthy_page_without_drag_is_not_slider_success():
    assert (
        summarize([success()[0], success()[3]])["counts"]["automatic_local_success"]
        == 0
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "pc1_manual"},
        {"completion_id": "another"},
        {"scope": "seed"},
        {"auth_state_confirmed": False},
    ],
)
def test_wrong_confirmation_not_counted(changes):
    rows = success() + [
        event(
            "auth_complete_result", 4, result={"confirmed": False, "result": payload()}
        ),
        event("auth_complete_confirmed", 5, result=payload(**changes)),
    ]
    assert summarize(rows)["counts"]["auth_confirmed"] == 0


def test_immediate_confirmation_and_duplicate_ack_count_once():
    rows = success() + [
        event(
            "auth_complete_result", 4, result={"confirmed": True, "result": payload()}
        ),
        event("auth_complete_confirmed", 5, result=payload()),
    ]
    assert summarize(rows)["counts"]["auth_confirmed"] == 1


def test_late_ack_does_not_belong_to_next_attempt():
    rows = success() + [
        event(
            "auth_complete_result", 4, result={"confirmed": False, "result": payload()}
        ),
        event("local_solver_start", 5),
        event("auth_complete_confirmed", 6, result=payload()),
    ]
    report = summarize(rows)
    assert report["attempts"][0]["auth_confirmed"]
    assert not report["attempts"][1]["auth_confirmed"]


def test_container_boundary_cannot_finish_previous_attempt():
    rows = success()
    rows[3]["container_id"] = "container-b"
    assert summarize(rows)["counts"]["automatic_local_success"] == 0


def test_unlinked_auth_is_separate():
    counts = summarize([event("auth_complete_confirmed", result=payload())])["counts"]
    assert counts["unlinked_auth_confirmations"] == 1
    assert counts["auth_confirmed"] == 0


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        "2026-10-06T12:00:00Z []",
        '2026-10-06T12:00:00Z {"kind":"unrelated","cookie":"secret"}',
    ],
)
def test_ignored_lines(line):
    assert project_line(line, "container") is None


def test_unknown_strings_and_nested_credentials_not_retained():
    row = event(
        "local_solver_end",
        success=False,
        failure_reason="token=secret",
        cookie={"value": "private"},
    )
    assert row["failure_reason"] == "other"
    assert "secret" not in json.dumps(row)
    assert "private" not in json.dumps(row)


def test_nanosecond_timestamp():
    assert timestamp("2026-10-06T12:00:00.123456789Z") == timestamp(
        "2026-10-06T12:00:00.123456Z"
    )
