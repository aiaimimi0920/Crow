"""Elapsed time alone never proves a human authentication gate is clear."""

import json
import os

import pytest

from src.runtime_state import RuntimeState
from src.solver_manual_flags import global_manual_pause_active


@pytest.mark.parametrize("content", ['{"paused":true}', "broken json", "[]"])
def test_old_unknown_flags_remain_gates_without_mutating_files(tmp_path, content):
    path = tmp_path / "force_unlock.flag"
    path.write_text(content, encoding="utf-8")
    os.utime(path, (1, 1))
    assert global_manual_pause_active(
        str(path), lambda _: "missing", lambda _: tmp_path / "missing"
    )
    assert path.read_text(encoding="utf-8") == content


def test_native_retry_does_not_expire_manual_only_pause(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    server._begin_solver_challenge({"scope": "detail", "node_id": "pc2"})
    assert server._mark_solver_manual_required(scope="detail", manual_only=True) is None
    path = server._solver_scope_state_path("detail")
    state = json.loads(path.read_text(encoding="utf-8"))
    state.update(first_seen_epoch=1.0, pause_started_epoch=1.0)
    assert server._persist_solver_scope_state("detail", state) is None
    before = path.read_bytes()
    result = server._trigger_manual_solver_retry_if_due(now=10000000000.0)
    assert result["queued"] is False
    assert path.read_bytes() == before
    assert server._solver_scope_runtime_status("detail")["manual_required"] is True
