"""A clear scope must not bypass an explicit suppressed-report retry floor."""

from types import SimpleNamespace

import pytest

from tools import detail_worker_wait as owner


@pytest.fixture
def clock(monkeypatch):
    state = {"now": 0.0, "polls": 0}
    monkeypatch.setattr(owner.time, "monotonic", lambda: state["now"])
    monkeypatch.setattr(owner.worker_lifecycle, "checkpoint", lambda _: True)
    monkeypatch.setattr(
        owner.worker_lifecycle,
        "wait",
        lambda seconds: state.update(now=state["now"] + seconds),
    )

    def fetch(*_args, **_kwargs):
        state["polls"] += 1
        if "status" in state:
            if isinstance(state["status"], Exception):
                raise state["status"]
            return state["status"]
        return {
            "paused": False,
            "collection_scopes": {
                "detail": {
                    "paused": False,
                    "manual_required": False,
                    "challenge_id": None,
                }
            },
        }

    monkeypatch.setattr(owner, "fetch_json", fetch)
    return state


def run_wait(status="recent_auth_complete", hint=142, *, seconds=900, scope="detail"):
    return owner.wait_after_detail_batch(
        SimpleNamespace(
            analysis_only=False, api_base_url="https://example.invalid/api"
        ),
        {
            "results": [
                {
                    "decision": "detail_item_retryable_failure",
                    "reason": "detail_stale_challenge_ignored",
                    "captcha_solver_report": {
                        "status": status,
                        "retry_after_seconds": hint,
                        **({"scope": scope} if scope is not None else {}),
                    },
                }
            ]
        },
        seconds,
    )


@pytest.mark.parametrize("status", ["recent_auth_complete", "recent_force_reset"])
@pytest.mark.parametrize("hint", [40, 43, 142, "142", 142.2])
def test_unchanged_clear_scope_cannot_skip_explicit_report_floor(clock, status, hint):
    receipt = run_wait(status, hint)
    assert clock["now"] >= float(hint)
    assert clock["now"] <= float(hint) + 30
    assert receipt["wait_exit"] == "report_backoff_elapsed"
    assert receipt["report_backoff_seconds"] >= float(hint)
    assert receipt["status_poll_count"] == clock["polls"] == 1
    assert receipt["requested_wait_seconds"] == 900


def test_planned_report_floor_is_honored_at_deadline(clock):
    receipt = run_wait(seconds=142)
    assert clock["now"] == 142
    assert receipt["report_backoff_seconds"] == 142


def test_short_caller_wait_cannot_override_longer_server_floor(clock):
    receipt = run_wait(seconds=10)
    assert clock["now"] >= 142
    assert receipt["requested_wait_seconds"] == 10


@pytest.mark.parametrize("hint", [None, "bad", -1, 0, True, float("nan"), float("inf")])
def test_invalid_hint_does_not_invent_a_report_floor(clock, hint):
    receipt = run_wait(hint=hint)
    assert clock["now"] == 30
    assert receipt["wait_exit"] == "detail_resumed"
    assert "report_backoff_seconds" not in receipt


@pytest.mark.parametrize(
    "status,scope",
    [
        ("stale_challenge", "detail"),
        ("other", "detail"),
        ("recent_force_reset", "seed"),
    ],
)
def test_unrelated_or_wrong_scope_report_does_not_expand_detail_backoff(
    clock, status, scope
):
    receipt = run_wait(status=status, scope=scope)
    assert clock["now"] == 30
    assert "report_backoff_seconds" not in receipt


def test_cancellation_during_report_floor_never_probes(clock, monkeypatch):
    monkeypatch.setattr(
        owner.worker_lifecycle, "checkpoint", lambda _: clock["now"] < 30
    )
    receipt = run_wait()
    assert clock["now"] == 30
    assert clock["polls"] == 0
    assert receipt["wait_exit"] == "stopping"


@pytest.mark.parametrize("scope", [None, ""])
def test_legacy_report_without_scope_still_honors_floor(clock, scope):
    receipt = run_wait(scope=scope)
    assert clock["now"] == 142
    assert receipt["report_backoff_seconds"] == 142
    assert receipt["wait_exit"] == "report_backoff_elapsed"


@pytest.mark.parametrize(
    "status",
    [
        {},
        None,
        OSError("offline"),
        TimeoutError("timeout"),
        ValueError("invalid json"),
        {"paused": False},
        {"paused": True},
        {"paused": False, "operator_paused": True},
        {"paused": True, "reason": "operator_paused"},
        {
            "paused": False,
            "captcha_solver": {"paused": True, "pause_reason": "operator"},
        },
        {"paused": False, "collection_scopes": {"detail": {"paused": True}}},
        {
            "paused": False,
            "collection_scopes": {"detail": {"paused": False, "manual_required": True}},
        },
        {
            "paused": False,
            "collection_scopes": {
                "detail": {
                    "paused": False,
                    "manual_required": False,
                    "challenge_id": "still-active",
                }
            },
        },
    ],
)
def test_elapsed_floor_does_not_override_blocked_or_unknown_state(clock, status):
    clock["status"] = status
    receipt = run_wait()
    assert clock["now"] == 900
    assert receipt["wait_exit"] == "deadline_elapsed"
    assert receipt["report_backoff_seconds"] == 142
    assert receipt["status_poll_count"] == clock["polls"] == 26


def test_seed_only_pause_can_resume_clear_detail_after_floor(clock):
    clock["status"] = {
        "paused": True,
        "collection_scopes": {
            "seed": {"paused": True},
            "detail": {"paused": False, "manual_required": False, "challenge_id": None},
        },
    }
    receipt = run_wait()
    assert clock["now"] == 142
    assert receipt["wait_exit"] == "report_backoff_elapsed"
    assert clock["polls"] == 1


def test_largest_report_floor_applies_to_whole_batch(clock):
    result = {
        "results": [
            {
                "reason": "detail_stale_challenge_ignored",
                "captcha_solver_report": {
                    "status": "recent_auth_complete",
                    "retry_after_seconds": hint,
                },
            }
            for hint in [40, 142.2, 43]
        ]
    }
    receipt = owner.wait_after_detail_batch(
        SimpleNamespace(
            analysis_only=False, api_base_url="https://example.invalid/api"
        ),
        result,
        900,
    )
    assert clock["now"] == 143
    assert receipt["report_backoff_seconds"] == 143
    assert clock["polls"] == 1
