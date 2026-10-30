"""An unconfirmed attempt must survive IPC without replacing its live document."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import pc2_solver_execution as execution
from tools import pc2_solver_loop_failure as failure
from tools import pc2_solver_retry_state as retry
from tools import pc2_solver_state_store as store

DEFERRED = (
    "cdp_unavailable",
    "challenge_loading",
    "slider_not_found",
    "slider_endpoint_unconfirmed",
    "cancelled",
    "deadline_exceeded",
    "execution_unavailable",
)
PROBE = {"_target_id": "loading-document"}


@pytest.fixture
def attempt(monkeypatch):
    solver = Mock(last_failure_reason="challenge_loading")
    solver.solve.return_value = False
    monkeypatch.setattr(execution, "_solver_class", lambda: lambda **_: solver)
    monkeypatch.setattr(execution, "log_event", lambda _: None)
    monkeypatch.setattr("tools.pc2_solver_diagnostics.log_event", lambda _: None)
    tabs = Mock()
    monkeypatch.setattr(execution, "record_failed_drags", tabs)
    return solver, tabs


@pytest.fixture
def process_context(monkeypatch):
    messages = []
    receiver = SimpleNamespace(
        poll=lambda: bool(messages), recv=lambda: messages.pop(0), close=lambda: None
    )
    sender = SimpleNamespace(send=messages.append, close=lambda: None)

    def process(*, target, args, name):
        return SimpleNamespace(
            start=lambda: target(*args),
            join=lambda _: None,
            is_alive=lambda: False,
            close=lambda: None,
            exitcode=0,
        )

    context = SimpleNamespace(Pipe=lambda **_: (receiver, sender), Process=process)
    monkeypatch.setattr(execution.multiprocessing, "get_context", lambda _: context)
    return context


@pytest.mark.parametrize("reason", DEFERRED + ("challenge_retry_exhausted",))
def test_child_preserves_known_failure_reason(attempt, reason):
    solver, _ = attempt
    solver.last_failure_reason = reason
    connection = Mock()
    execution._run_solver_process_entry(connection, "offline", "target", 1, PROBE, 0)
    assert connection.send.call_args.args[0] == {
        "success": False,
        "failure_reason": reason,
    }
    connection.close.assert_called_once()


@pytest.mark.parametrize("reason", DEFERRED)
def test_uncertain_result_keeps_target_but_consumes_existing_budget(
    monkeypatch, reason
):
    rotate, browse, report = Mock(), Mock(), Mock()
    monkeypatch.setattr(failure, "rotate_failed_challenge_target", rotate)
    monkeypatch.setattr(failure, "maybe_browse_reference_tabs", browse)
    monkeypatch.setattr(failure, "_report_manual_captcha", report)
    monkeypatch.setattr(failure, "manual_fallback_enabled", lambda: True)
    monkeypatch.setattr(failure, "FALLBACK_FAIL_THRESHOLD", 1)
    monkeypatch.setattr(failure, "FALLBACK_STALL_SECONDS", 0)
    monkeypatch.setattr(failure, "log_event", lambda _: None)
    monkeypatch.setattr(failure, "time", SimpleNamespace(time=lambda: 1000.0))
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 2)
    monkeypatch.setattr(retry, "SOLVER_COOLDOWN_SECONDS", 180.0)
    state = store._default_fallback_state()
    state.update(challenge_id="detail-1", scope="detail", slider_attempts=1)
    store._save_fallback_state(state)

    assert (
        failure.record_failed_attempt(
            "offline", "offline", "target", PROBE, failure_reason=reason
        )
        is PROBE
    )
    saved = store._load_fallback_state()
    assert saved["slider_attempts"] == saved["consecutive_failures"] == 2
    assert saved["solver_cooldown_until"] == 1180.0
    assert saved["slider_next_attempt_at"] is None
    rotate.assert_not_called()
    browse.assert_not_called()
    report.assert_not_called()


@pytest.mark.parametrize(
    "reason,expected",
    [(reason, reason) for reason in DEFERRED]
    + [("private-token", "other"), ({"private-token": 1}, "other")],
)
def test_reason_crosses_child_parent_boundary(
    attempt, process_context, reason, expected
):
    solver, tabs = attempt
    solver.last_failure_reason = reason
    details = {"failure_reason": "stale"}
    assert (
        execution.run_solver_local_with_deadline(
            "offline", "target", timeout_seconds=2, failure_details=details
        )
        is False
    )
    assert details == {"failure_reason": expected}
    if reason in DEFERRED:
        tabs.assert_called_once_with("offline", 0, allow_open=False)


@pytest.mark.parametrize("timeout", [0, 2])
def test_success_clears_previous_failure(attempt, process_context, timeout):
    solver, tabs = attempt
    solver.solve.return_value = True
    details = {"failure_reason": "cancelled"}
    assert (
        execution.run_solver_local_with_deadline(
            "offline", "target", timeout_seconds=timeout, failure_details=details
        )
        is True
    )
    assert details == {}
    tabs.assert_called_once_with("offline", 0)


@pytest.mark.parametrize("timeout", [0, 2])
def test_manual_challenge_still_uses_terminal_handoff(
    attempt, process_context, timeout
):
    attempt[0].last_failure_reason = "manual_required"
    with pytest.raises(execution.ManualChallengeRequired):
        execution.run_solver_local_with_deadline(
            "offline", "target", timeout_seconds=timeout, failure_details={}
        )


@pytest.mark.parametrize("timeout", [0, 2])
def test_solver_exception_is_not_a_confirmed_rejection(
    attempt, process_context, timeout
):
    attempt[0].solve.side_effect = RuntimeError("offline fixture")
    details = {}
    assert (
        execution.run_solver_local_with_deadline(
            "offline", "target", timeout_seconds=timeout, failure_details=details
        )
        is False
    )
    assert details == {"failure_reason": "execution_unavailable"}
    attempt[1].assert_called_once_with("offline", 0, allow_open=False)


@pytest.mark.parametrize("reason", [None, "challenge_retry_exhausted", "unknown"])
def test_confirmed_or_legacy_failure_retains_rotation(monkeypatch, reason):
    rotate, browse = Mock(return_value={"probe_target": PROBE}), Mock()
    monkeypatch.setattr(failure, "rotate_failed_challenge_target", rotate)
    monkeypatch.setattr(failure, "maybe_browse_reference_tabs", browse)
    monkeypatch.setattr(failure, "manual_fallback_enabled", lambda: False)
    monkeypatch.setattr(failure, "log_event", lambda _: None)
    assert (
        failure.record_failed_attempt(
            "offline", "offline", "target", PROBE, failure_reason=reason
        )
        is PROBE
    )
    rotate.assert_called_once_with("offline", "target", probe_target=PROBE)
    browse.assert_called_once_with("offline", "offline", PROBE)


def test_killed_child_is_an_unconfirmed_deadline(process_context):
    alive = [True]
    process = SimpleNamespace(
        start=lambda: None,
        join=lambda _: None,
        close=lambda: None,
        is_alive=lambda: alive[0],
        terminate=lambda: alive.__setitem__(0, False),
        exitcode=None,
    )
    process_context.Process = lambda **_: process
    details = {}
    assert (
        execution.run_solver_local_with_deadline(
            "offline", "target", timeout_seconds=1, failure_details=details
        )
        is False
    )
    assert details == {"failure_reason": "deadline_exceeded"}


def _send_spawn_failure(connection, *_):
    connection.send({"success": False, "failure_reason": "challenge_loading"})
    connection.close()


def test_real_spawn_pipe_retains_failure_metadata(monkeypatch):
    context = execution.multiprocessing.get_context("spawn")
    monkeypatch.setattr(
        execution.multiprocessing,
        "get_context",
        lambda _: SimpleNamespace(
            Pipe=context.Pipe,
            Process=lambda **kwargs: context.Process(
                **{**kwargs, "target": _send_spawn_failure}
            ),
        ),
    )
    details = {}
    assert (
        execution.run_solver_local_with_deadline(
            "offline",
            "target",
            timeout_seconds=8,
            failure_details=details,
        )
        is False
    )
    assert details == {"failure_reason": "challenge_loading"}


def test_uncertain_completed_drags_remain_counted_without_opening_pages(monkeypatch):
    from tools import pc2_solver_reference_tabs as tabs

    state, targets, opened = {}, Mock(), Mock()
    monkeypatch.setattr(tabs, "_load_fallback_state", lambda: {"challenge_id": "one"})
    monkeypatch.setattr(tabs, "load_reference_state", lambda: state)
    monkeypatch.setattr(tabs, "save_reference_state", state.update)
    monkeypatch.setattr(tabs, "list_cdp_targets", targets)
    monkeypatch.setattr(tabs, "open_background_page", opened)
    tabs.record_failed_drags("offline", 3, allow_open=False)
    assert state["failed_drags"] == 3
    targets.assert_not_called()
    opened.assert_not_called()
