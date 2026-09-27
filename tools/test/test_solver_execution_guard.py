"""Native guard host replacement and polling cancellation contracts."""

from types import SimpleNamespace

import pytest


@pytest.fixture(params=[False, True])
def host(request, monkeypatch):
    from src import server, server_handler_core
    from src.runtime_state import RuntimeState

    module = server if request.param else server_handler_core
    monkeypatch.setattr(module, "RUNTIME", RuntimeState())
    return module


def test_guard_native_owner_survives_late_handler_publication(host):
    from src.solver_execution_guard import SolverExecutionGuard

    for name in SolverExecutionGuard.__all__:
        assert isinstance(getattr(host, name).__self__, SolverExecutionGuard)
        if host.__name__ == "src.server":
            assert getattr(host._CONTEXT, name) is getattr(host, name)


def test_saved_guard_rejects_replacement_at_same_timestamp(host, monkeypatch):
    from src.runtime_state import RuntimeState

    current, cancelled = (
        host._solver_execution_is_current,
        host._solver_execution_cancelled,
    )
    state = host.RUNTIME
    execution = state.solver.begin(10.0, resume_epoch=0, cancel_epoch=0)
    assert current(execution) and not cancelled(execution)
    replacement = RuntimeState()
    new_execution = replacement.solver.begin(10.0, resume_epoch=0, cancel_epoch=0)
    monkeypatch.setattr(host, "RUNTIME", replacement)
    assert not current(execution) and cancelled(execution)
    assert current(new_execution) and not cancelled(new_execution)
    assert state.solver.current is execution


@pytest.mark.parametrize("reason", ["resume", "cancel", "event"])
def test_independent_cancellation_sources_stop_execution(host, reason):
    execution = host.RUNTIME.solver.begin(1, resume_epoch=0, cancel_epoch=0)
    if reason == "resume":
        host.RUNTIME.recovery.resume(2)
    elif reason == "cancel":
        host.RUNTIME.recovery.cancel(2)
    else:
        execution.cancelled.set()
    assert host._solver_execution_cancelled(execution)
    assert host._solver_execution_is_current(execution)
    assert host._solver_execution_resumed(execution) == (reason == "resume")


def test_saved_poll_uses_current_clock_and_predicates_without_sleep(host, monkeypatch):
    execution = host.RUNTIME.solver.begin(1, resume_epoch=0, cancel_epoch=0)
    poll = host._wait_for_solver_manual_poll
    times = iter([10.0, 10.0])
    monkeypatch.setattr(host, "time", SimpleNamespace(monotonic=lambda: next(times)))
    monkeypatch.setattr(host, "_solver_execution_is_current", lambda execution: False)
    assert poll(execution, 20) is False
    times = iter([20.0, 20.0, 20.0])
    assert poll(execution, 20) is False


def test_manual_poll_distinguishes_supersession_from_cancellation(host, monkeypatch):
    execution = host.RUNTIME.solver.begin(1, resume_epoch=0, cancel_epoch=0)
    execution.cancelled.set()
    calls = []
    times = iter([10.0, 10.0, 10.0])
    monkeypatch.setattr(host, "time", SimpleNamespace(monotonic=lambda: next(times)))
    monkeypatch.setattr(
        execution.superseded, "wait", lambda seconds: calls.append(seconds) or True
    )
    assert host._wait_for_solver_manual_poll(execution, 20) is False
    assert calls == [0.1]
