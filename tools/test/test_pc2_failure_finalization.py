"""Completed failures are accounted before fallible cleanup or control I/O."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveStopped
from src.captcha_deferral import TargetNavigationUnconfirmed
from tools import pc2_solver_loop_failure as failure
from tools import pc2_solver_retry_state as retry
from tools import pc2_solver_state_store as store

CDP = "http://127.0.0.1:9223"
TARGET = "https://sf-item.taobao.com/sf_item/123.htm"


@pytest.fixture
def failed_attempt(monkeypatch):
    state = store._default_fallback_state()
    state.update(
        challenge_id="current",
        scope="detail",
        slider_attempt_started_at=999.0,
        window_started_at=10.0,
    )
    store._save_fallback_state(state)
    events = []
    monkeypatch.setattr(failure, "time", SimpleNamespace(time=lambda: 1000.0))
    monkeypatch.setattr(failure, "log_event", events.append)
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 2)
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_SECONDS", 180.0)
    monkeypatch.setattr(retry, "SLIDER_RETRY_INTERVAL_SECONDS", 5.0)
    browse, report = Mock(), Mock()
    monkeypatch.setattr(failure, "maybe_browse_reference_tabs", browse)
    monkeypatch.setattr(failure, "_report_manual_captcha", report)
    monkeypatch.setattr(failure, "manual_fallback_enabled", lambda: True)
    return SimpleNamespace(events=events, browse=browse, report=report)


def call_failure(**kwargs):
    return failure.record_failed_attempt(
        "http://api.test",
        CDP,
        TARGET,
        None,
        failure_reason="challenge_retry_exhausted",
        **kwargs,
    )


@pytest.mark.parametrize(
    "error_type", [TargetNavigationUnconfirmed, OSError, SolveStopped]
)
def test_rotation_exception_cannot_lose_failure_or_shared_cooldown(
    monkeypatch, failed_attempt, error_type
):
    snapshots = []

    def rotate(*_args, **_kwargs):
        snapshots.append(store._load_fallback_state())
        raise error_type()

    monkeypatch.setattr(failure, "rotate_failed_challenge_target", rotate)
    for _ in range(2):
        with pytest.raises(error_type):
            call_failure()

    first, second = snapshots
    assert first["slider_attempts"] == first["consecutive_failures"] == 1
    assert first["slider_attempt_started_at"] is None
    assert first["slider_next_attempt_at"] == 1005.0
    assert second["slider_attempts"] == second["consecutive_failures"] == 2
    assert second["solver_cooldown_until"] == 1180.0
    assert second["solver_cooldown_cycles"] == 1
    assert second["slider_next_attempt_at"] is None
    assert store._load_fallback_state() == second
    failed_attempt.browse.assert_not_called()
    failed_attempt.report.assert_not_called()
    assert sum(e["kind"] == "slider_attempt_failed" for e in failed_attempt.events) == 2
    assert (
        sum(e["kind"] == "solver_cooldown_started" for e in failed_attempt.events) == 1
    )


def test_fresh_status_error_cannot_lose_completed_failure(monkeypatch, failed_attempt):
    rotate = Mock()
    monkeypatch.setattr(failure, "rotate_failed_challenge_target", rotate)

    def read(_api):
        state = store._load_fallback_state()
        assert state["slider_attempts"] == state["consecutive_failures"] == 1
        assert state["slider_attempt_started_at"] is None
        raise OSError("fixture control read failed")

    monkeypatch.setattr(failure, "read_solver_status", read)
    with pytest.raises(OSError, match="fixture control read failed"):
        call_failure(solver_status={"scope": "detail"}, expected_node_id="pc2")
    assert store._load_fallback_state()["slider_next_attempt_at"] == 1005.0
    rotate.assert_not_called()
    failed_attempt.browse.assert_not_called()
    failed_attempt.report.assert_not_called()
