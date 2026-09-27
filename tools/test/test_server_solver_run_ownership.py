"""Late solver results must not mutate a replacement run or its auth lock."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    from src import server
    from src.runtime_state import RuntimeState

    state = RuntimeState()
    state.control.set_pause(True, "captcha_solver")
    monkeypatch.setattr(server, "RUNTIME", state)
    monkeypatch.setattr(server.time, "time", lambda: 1000.0)
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_challenge_scope_for_request", lambda _request: "")
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", dict)
    monkeypatch.setattr(server, "_solver_worker_quiesce_seconds", lambda: 0)
    monkeypatch.setattr(server, "_wait_for_solver_cdp_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(server, "_mark_solver_manual_required", Mock())
    monkeypatch.setattr(server, "_clear_auth_lock_after_solver_success", Mock())
    return server


def replace_run(server):
    server._clear_solver_running_state()
    activated, reason, started_at = server._activate_solver_submission(
        {"target_url": "https://contest.local/new-challenge"}, None
    )
    assert activated and reason == "started"
    return started_at


def test_solver_runner_uses_native_function_with_handler_descriptor(runtime):
    from src import solver_run_binding

    handler = object.__new__(runtime.DataHandler)
    assert handler.run_solver.__self__ is handler
    assert handler.run_solver.__func__ is runtime.run_solver
    assert runtime.run_solver.__module__ == solver_run_binding.__name__
    assert runtime.run_solver.__name__ == "run_solver"
    assert runtime._CONTEXT.run_solver is runtime.run_solver
    assert not hasattr(runtime, "_IMPLEMENTATION_MODULES")


def test_handler_file_adapter_resolves_current_writer(runtime, monkeypatch):
    calls = []
    handler = object.__new__(runtime.DataHandler)
    saved = handler.update_file
    monkeypatch.setattr(runtime, "update_file_global", lambda *args: calls.append(args))
    data = {"value": 1}
    assert saved("file.json", "id", data) is None
    assert calls == [("file.json", "id", data)]
    assert handler.log_message("%s", "private") is None


@pytest.mark.parametrize("outcome", ["success", "failure", "exception"])
def test_late_solver_result_does_not_publish_over_replacement(
    runtime, monkeypatch, outcome
):
    started = threading.Event()
    release = threading.Event()

    class Solver:
        last_failure_reason = "manual_required"

        def solve(self):
            started.set()
            assert release.wait(5)
            if outcome == "exception":
                raise RuntimeError("old solver failed")
            return outcome == "success"

    monkeypatch.setattr(runtime, "_build_solver_for_request", lambda _request: Solver())
    handler = object.__new__(runtime.DataHandler)
    worker = threading.Thread(target=handler.run_solver, daemon=True)
    worker.start()
    try:
        assert started.wait(5)
        replacement_started_at = replace_run(runtime)
        replacement_finished_at = runtime.RUNTIME.solver.finished_at
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert runtime.RUNTIME.solver.running is True
    assert runtime.RUNTIME.solver.started_at == replacement_started_at
    assert runtime.RUNTIME.solver.last_status == "running"
    assert runtime.RUNTIME.solver.failure_reason is None
    assert runtime.RUNTIME.solver.finished_at == replacement_finished_at
    assert runtime.RUNTIME.control.paused is True
    runtime._mark_solver_manual_required.assert_not_called()
    runtime._clear_auth_lock_after_solver_success.assert_not_called()


def test_late_success_preserves_new_manual_verification_request(runtime, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    class Solver:
        def solve(self):
            started.set()
            assert release.wait(5)
            return True

    monkeypatch.setattr(runtime, "_build_solver_for_request", lambda _request: Solver())
    handler = object.__new__(runtime.DataHandler)
    worker = threading.Thread(target=handler.run_solver, daemon=True)
    worker.start()
    try:
        assert started.wait(5)
        runtime._request_solver_cancel()
        with runtime.RUNTIME.lock:
            runtime.RUNTIME.solver.record_outcome("manual_required", "manual_required")
            runtime.RUNTIME.control.reason = "manual_required"
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert runtime.RUNTIME.solver.running is False
    assert runtime.RUNTIME.solver.last_status == "manual_required"
    assert runtime.RUNTIME.solver.failure_reason == "manual_required"
    assert runtime.RUNTIME.control.paused is True
    runtime._clear_auth_lock_after_solver_success.assert_not_called()


def test_stale_auth_preflight_cannot_clear_replacement_challenge(runtime, monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class Solver:
        def _preflight_current_challenge(self):
            entered.set()
            assert release.wait(5)
            return {"already_authenticated": True}

    monkeypatch.setattr(runtime, "_build_solver_for_request", lambda _request: Solver())
    monkeypatch.setattr(
        runtime, "_captcha_solver_runtime_status", lambda: {"manual_required": True}
    )
    handler = object.__new__(runtime.DataHandler)
    worker = threading.Thread(target=handler.run_solver, daemon=True)
    worker.start()
    try:
        assert entered.wait(5)
        replace_run(runtime)
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert runtime.RUNTIME.solver.running is True
    runtime._clear_auth_lock_after_solver_success.assert_not_called()


def test_new_run_is_not_cancelled_by_previous_run_at_same_timestamp(
    runtime, monkeypatch
):
    replace_run(runtime)
    runtime._request_solver_cancel()
    runtime._clear_solver_running_state()

    class Solver:
        calls = 0

        def solve(self):
            assert not self.cancel_checker()
            self.calls += 1
            return True

    solver = Solver()
    monkeypatch.setattr(runtime, "_build_solver_for_request", lambda _request: solver)
    object.__new__(runtime.DataHandler).run_solver()
    assert solver.calls == 1
    runtime._clear_auth_lock_after_solver_success.assert_called_once()


def test_replacing_run_interrupts_manual_poll_wait(runtime, monkeypatch):
    replace_run(runtime)
    execution = runtime.RUNTIME.solver.current
    entered = threading.Event()
    finished = threading.Event()
    results = []
    original_wait = execution.superseded.wait

    def observed_wait(timeout):
        entered.set()
        return original_wait(timeout)

    def poll():
        results.append(
            runtime._wait_for_solver_manual_poll(execution, time.monotonic() + 10)
        )
        finished.set()

    monkeypatch.setattr(execution.superseded, "wait", observed_wait)
    worker = threading.Thread(target=poll, daemon=True)
    worker.start()
    try:
        assert entered.wait(5)
        replace_run(runtime)
        assert finished.wait(1), (
            "The superseded worker remained in its two-second poll wait"
        )
    finally:
        execution.superseded.set()
        worker.join(5)
    assert results == [False]


def test_solver_execution_snapshot_is_atomic_and_preserves_identity():
    from src.solver_execution_state import SolverExecutionState

    state = SolverExecutionState()
    empty = state.snapshot()
    assert empty.execution is None
    assert empty.started_at is None
    assert empty.cancelled is False
    assert empty.superseded is False

    execution = state.begin(12.5, resume_epoch=3.0, cancel_epoch=4.0)
    active = state.snapshot()
    assert active.execution is execution
    assert (active.started_at, active.resume_epoch, active.cancel_epoch) == (
        12.5,
        3.0,
        4.0,
    )
    assert active.cancelled is False
    assert active.superseded is False

    state.cancel()
    cancelled = state.snapshot()
    assert cancelled.execution is execution
    assert cancelled.cancelled is True
    assert state.owns(cancelled.execution)

    state.clear()
    cleared = state.snapshot()
    assert cleared.execution is None
    assert execution.superseded.is_set()


def test_concurrent_solver_reservations_preserve_newer_submission_token():
    from src.solver_execution_state import SolverExecutionState

    state = SolverExecutionState()
    ready = threading.Barrier(8)

    def reserve(_index):
        ready.wait(timeout=5)
        return state.reserve()

    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = [token for token in pool.map(reserve, range(8)) if token is not None]
    assert len(tokens) == 1
    old_token = tokens[0]
    assert state.snapshot().pending_token is old_token

    state.clear()
    new_token = state.reserve()
    assert new_token is not None and new_token is not old_token
    state.release(old_token)
    before = state.snapshot()
    assert before.pending_token is new_token
    assert state.activate(10.0, token=old_token, resume_epoch=0, cancel_epoch=0) == (
        False,
        "stale_submission",
        0.0,
    )
    assert state.activate(10.0, token=None, resume_epoch=0, cancel_epoch=0) == (
        False,
        "submission_pending",
        0.0,
    )
    assert state.snapshot() == before
    assert state.activate(10.0, token=new_token, resume_epoch=0, cancel_epoch=0) == (
        True,
        "started",
        10.0,
    )
    assert state.reserve() is None
    assert state.snapshot().pending_token is None


def test_solver_outcome_and_finish_reject_replaced_execution_at_same_timestamp():
    from src.solver_execution_state import SolverExecutionState

    state = SolverExecutionState()
    old = state.begin(0.0, resume_epoch=0, cancel_epoch=0)
    assert state.snapshot().started_at == 0.0
    replacement = state.begin(0.0, resume_epoch=0, cancel_epoch=0)
    before = state.snapshot()

    assert not state.record_outcome("error", "stale failure", execution=old)
    assert not state.finish(old, 11.0)
    assert state.snapshot() == before
    assert state.record_outcome("solved", execution=replacement)
    assert state.finish(replacement, 12.0)
    finished = state.snapshot()
    assert finished.execution is replacement
    assert not finished.running
    assert (finished.last_status, finished.failure_reason, finished.finished_at) == (
        "solved",
        None,
        12.0,
    )


def test_solver_clear_invalidates_inflight_and_queued_work_without_losing_finish_time():
    from src.solver_execution_state import SolverExecutionState

    state = SolverExecutionState()
    execution = state.begin(5.0, resume_epoch=0, cancel_epoch=0)
    state.require_manual()
    state.clear(finished_at=8.0)
    assert execution.cancelled.is_set() and execution.superseded.is_set()
    assert not state.finish(execution, 9.0)
    token = state.reserve()
    state.clear(finished_at=10.0)
    snapshot = state.snapshot()
    assert snapshot.execution is None
    assert not snapshot.running
    assert snapshot.pending_token is None
    assert snapshot.finished_at == 8.0
    assert snapshot.last_status == "manual_required"
    assert (
        state.activate(11.0, token=token, resume_epoch=0, cancel_epoch=0)[1]
        == "stale_submission"
    )
