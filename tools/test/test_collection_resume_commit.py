"""Resume must commit durable cleanup before releasing collection or solver state."""

from pathlib import Path

import pytest

from src.runtime_state import RuntimeState


@pytest.mark.parametrize("failure", ["flag", "challenge"])
@pytest.mark.parametrize("operator_paused", [False, True])
def test_failed_resume_stays_paused_until_cleanup_succeeds(
    monkeypatch, tmp_path, failure, operator_paused
):
    from src import server

    runtime = RuntimeState()
    monkeypatch.setattr(server, "RUNTIME", runtime)
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    runtime.control.set_pause(operator_paused, "operator" if operator_paused else None)
    runtime.solver.record_outcome("manual_required", "manual_required")
    assert (
        server._persist_solver_scope_state(
            "seed",
            {
                "challenge_id": "blocked",
                "paused": True,
                "last_request": {"target_url": "https://sf.taobao.com/list/1.htm"},
            },
        )
        is None
    )
    flag = Path(server._solver_force_unlock_flag_path())
    flag.write_text("manual", encoding="utf-8")
    receipt = server._solver_scope_state_path("seed")
    original = receipt.read_bytes()
    before = runtime.solver.snapshot()
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", dict)
    monkeypatch.setattr(server, "_collection_runtime_state_label", lambda: "test")
    remove, unlink = server.os.remove, Path.unlink

    def fail_remove(path, *args, **kwargs):
        if Path(path) == flag:
            raise PermissionError("flag locked")
        return remove(path, *args, **kwargs)

    def fail_unlink(path, *args, **kwargs):
        if path == receipt:
            raise PermissionError("receipt locked")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        if failure == "flag":
            fault.setattr(server.os, "remove", fail_remove)
        else:
            fault.setattr(Path, "unlink", fail_unlink)
        result = server._collection_observer_runtime_control_payload("resume")
        assert result["ok"] is False
        assert result["paused"] is True
        assert runtime.control.snapshot().paused is True
        assert runtime.recovery.snapshot().resume_epoch == 0
        assert runtime.solver.snapshot() == before
        assert receipt.read_bytes() == original

    result = server._collection_observer_runtime_control_payload("resume")
    assert result["ok"] is True
    assert result["paused"] is False
    assert runtime.recovery.snapshot().resume_epoch > 0
    assert not receipt.exists()
    assert not flag.exists()


def test_resume_holds_runtime_lock_during_durable_cleanup(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from src import server

    runtime = RuntimeState()
    runtime.control.set_pause(True, "operator")
    monkeypatch.setattr(server, "RUNTIME", runtime)
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", dict)
    monkeypatch.setattr(server, "_collection_runtime_state_label", lambda: "test")
    clear = server._clear_solver_challenge_state
    acquisitions = []

    def probe():
        acquired = runtime.lock.acquire(blocking=False)
        if acquired:
            runtime.lock.release()
        return acquired

    with ThreadPoolExecutor(max_workers=1) as pool:

        def checked_clear():
            acquisitions.append(pool.submit(probe).result(timeout=5))
            assert runtime.control.snapshot().paused is True
            assert runtime.recovery.snapshot().resume_epoch == 0
            return clear()

        monkeypatch.setattr(server, "_clear_solver_challenge_state", checked_clear)
        assert server._collection_observer_runtime_control_payload("resume")["ok"]
    assert acquisitions == [False]
    assert runtime.control.snapshot().paused is False
