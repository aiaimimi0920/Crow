"""Selected automatic work keeps scope ownership through success and failure."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import pc2_solver_loop as loop
from tools import pc2_solver_loop_failure as failure
from tools import pc2_solver_retry_state as retry
from tools.test import test_pc2_solver_work_selection_loop as selection_tests

work_loop = selection_tests.work_loop


@pytest.mark.parametrize("success", [False, True])
def test_dispatched_work_keeps_receipt_scope_and_shared_failure_history(
    work_loop, monkeypatch, success
):
    status, state, original, _probes, saved, _events, poll = work_loop
    state["manual_pushed"] = True
    target = status["scopes"]["detail"]["last_request"]["target_url"]
    probe = {"_target_id": "detail-page", "_target_url": target}

    def persisted():
        return deepcopy(saved[-1] if saved else state)

    monkeypatch.setattr(loop, "_load_fallback_state", persisted)
    monkeypatch.setattr(failure, "_load_fallback_state", persisted)
    monkeypatch.setattr(
        failure, "_save_fallback_state", lambda value: saved.append(deepcopy(value))
    )
    monkeypatch.setattr(loop, "write_solver_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(loop, "check_cdp_healthy", lambda _: True)
    monkeypatch.setattr(
        loop, "probe_requested_targets", lambda *_a, **_k: (probe, target)
    )
    monkeypatch.setattr(failure, "read_solver_status", lambda _: deepcopy(status))
    monkeypatch.setattr(failure, "time", SimpleNamespace(time=lambda: 300.0))
    monkeypatch.setattr(failure, "log_event", lambda _: None)
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 100)
    rotate, browse, report = Mock(), Mock(), Mock()
    monkeypatch.setattr(failure, "rotate_failed_challenge_target", rotate)
    monkeypatch.setattr(failure, "maybe_browse_reference_tabs", browse)
    monkeypatch.setattr(failure, "_report_manual_captcha", report)
    monkeypatch.setattr(failure, "manual_fallback_enabled", lambda: True)
    dispatched = []

    def solve(cdp, selected_target, **kwargs):
        dispatched.append((cdp, selected_target, kwargs, persisted()))
        if not success:
            status["scopes"]["detail"].update(
                challenge_id=None,
                paused=False,
                manual_required=False,
                last_status="manual_auth_completed",
                last_request={},
            )
            kwargs["failure_details"]["failure_reason"] = "challenge_retry_exhausted"
        return success

    monkeypatch.setattr(loop, "run_solver_local_with_deadline", solve)
    confirmation = Mock(return_value={"confirmed": False})
    monkeypatch.setattr(loop, "confirm_local_solver_success", confirmation)

    poll()

    assert len(dispatched) == 1
    _cdp, selected_target, kwargs, started_state = dispatched[0]
    assert selected_target == target
    assert kwargs["probe_target"] is probe
    assert started_state["scope"] == "detail"
    assert started_state["challenge_id"] == "detail-one"
    assert started_state["consecutive_failures"] == 7
    assert started_state["window_started_at"] == 100
    assert started_state["slider_next_attempt_at"] == 200
    assert started_state["manual_pushed"] is False
    assert status["scopes"]["seed"] == original["scopes"]["seed"]
    rotate.assert_not_called()
    browse.assert_not_called()
    report.assert_not_called()
    if success:
        confirmation.assert_called_once()
        submitted = confirmation.call_args.args
        assert submitted[1]["scope"] == "detail"
        assert submitted[1]["challenge_id"] == "detail-one"
        assert submitted[2] == target
    else:
        confirmation.assert_not_called()
        assert saved[-1]["consecutive_failures"] == 8
        assert saved[-1]["slider_attempts"] == 1
        assert saved[-1]["manual_pushed"] is False
