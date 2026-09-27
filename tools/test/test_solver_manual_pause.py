"""Manual pause remains active when scoped or compatibility flag writes fail."""

import builtins
import json
from pathlib import Path

import pytest

from src.runtime_state import RuntimeState


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("failure", ["scoped", "legacy", "both"])
def test_flag_failure_keeps_manual_pause_and_attempts_both_flags(
    monkeypatch, tmp_path, scope, failure
):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    server._begin_solver_challenge({"scope": scope, "node_id": "pc2"})
    server.RUNTIME.solver.running = True
    scoped = Path(server._solver_scope_manual_flag_path(scope))
    legacy = Path(server._solver_force_unlock_flag_path())
    failed = (
        {scoped, legacy}
        if failure == "both"
        else {scoped if failure == "scoped" else legacy}
    )
    opened = []
    open_file = builtins.open

    def fail_flag(path, *args, **kwargs):
        selected = Path(path)
        if selected in {scoped, legacy} and args and args[0] == "w":
            opened.append(selected)
            if selected in failed:
                raise PermissionError(f"locked {selected.name}")
        return open_file(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(builtins, "open", fail_flag)
        error = server._mark_solver_manual_required(scope=scope, manual_only=True)

    first_failure = scoped if scoped in failed else legacy
    assert error is not None and first_failure.name in error
    assert opened == [scoped, legacy]
    assert server.RUNTIME.recovery.snapshot().cancel_epoch > 0
    assert server.RUNTIME.recovery.snapshot().manual_only is True
    assert server._solver_scope_runtime_status(scope)["manual_only"] is True
    assert server._collection_effectively_paused() is True
    for path in {scoped, legacy} - failed:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["manual_only"] is True
        assert payload["last_request"]["node_id"] == "pc2"

    assert server._mark_solver_manual_required(scope=scope, manual_only=True) is None
    assert all(path.exists() for path in (scoped, legacy))
