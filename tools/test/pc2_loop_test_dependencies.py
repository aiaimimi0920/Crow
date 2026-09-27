"""Replace shared loop test dependencies at their explicit native call sites."""

from tools import (
    pc2_solver_loop,
    pc2_solver_loop_control,
    pc2_solver_loop_failure,
    pc2_solver_loop_probe,
)


def patch_loop_dependency(monkeypatch, name, value):
    owners = [
        owner
        for owner in (
            pc2_solver_loop,
            pc2_solver_loop_control,
            pc2_solver_loop_failure,
            pc2_solver_loop_probe,
        )
        if hasattr(owner, name)
    ]
    if not owners:
        raise AssertionError(f"No loop call site imports {name}")
    for owner in owners:
        monkeypatch.setattr(owner, name, value)
