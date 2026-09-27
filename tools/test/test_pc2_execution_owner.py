"""Native execution identity and child IPC failure handling."""

import pytest

from tools import pc2_solver_execution as execution


def test_execution_exports_retain_native_identity():
    from tools import pc2_local_solver

    for name in execution.__all__:
        original = getattr(execution, name)
        assert getattr(pc2_local_solver, name) is original
        assert original.__globals__ is vars(execution)


@pytest.mark.parametrize("disconnected", [False, True])
def test_child_exit_publishes_failure_and_closes_result_pipe(monkeypatch, disconnected):
    class Pipe:
        def __init__(self):
            self.result = None
            self.closed = False

        def send(self, result):
            self.result = result
            if disconnected:
                raise BrokenPipeError("parent exited")

        def close(self):
            self.closed = True

    def fail(*_args, **_kwargs):
        raise SystemExit(75)

    monkeypatch.setattr(execution, "run_solver_local", fail)
    pipe = Pipe()
    execution._run_solver_process_entry(
        pipe, "http://127.0.0.1:1", "https://example.invalid/", 1, None, 0
    )
    assert pipe.closed
    assert pipe.result == {"success": False, "error": "SystemExit(75)"}
