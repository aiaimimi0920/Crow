"""Scoped completion must not release an independently owned legacy pause."""

from pathlib import Path

import pytest

from src.runtime_state import RuntimeState


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("legacy_scope", [None, "same"])
@pytest.mark.parametrize("failure", [None, "scoped_flag", "scoped_receipt"])
def test_automated_success_preserves_independent_legacy_pause(
    monkeypatch, tmp_path, scope, legacy_scope, failure
):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    request = {"scope": scope, "node_id": "pc2"}
    challenge_id = server._begin_solver_challenge(request)
    assert server._mark_solver_manual_required(scope=scope, manual_only=True) is None
    legacy_request = {"node_id": "legacy-node"}
    if legacy_scope:
        legacy_request["scope"] = scope
    assert server._persist_solver_challenge_state("legacy-id", legacy_request) is None
    server.RUNTIME.recovery.set_challenge("legacy-id", legacy_request)
    assert server._mark_solver_manual_required(manual_only=True) is None
    paths = [
        server._solver_challenge_state_path(),
        Path(server._solver_force_unlock_flag_path()),
    ]
    durable_before = {path: path.read_bytes() for path in paths}
    recovery_before = server.RUNTIME.recovery.snapshot()
    solver_before = server.RUNTIME.solver.snapshot()
    pause_before = server.RUNTIME.control.snapshot()

    blocked = (
        Path(server._solver_scope_manual_flag_path(scope))
        if failure == "scoped_flag"
        else server._solver_scope_state_path(scope)
    )
    unlink = Path.unlink

    def fail_target(path, *args, **kwargs):
        if path == blocked:
            raise PermissionError("scoped cleanup locked")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        if failure:
            fault.setattr(Path, "unlink", fail_target)
        server._clear_auth_lock_after_solver_success(scope)

    if failure:
        scoped = server._solver_scope_runtime_status(scope)
        assert scoped["challenge_id"] == challenge_id
        assert scoped["paused"] is True
        assert scoped["manual_only"] is True
        assert server.RUNTIME.recovery.snapshot() == recovery_before
        assert server.RUNTIME.solver.snapshot() == solver_before
        assert {path: path.read_bytes() for path in paths} == durable_before
        server._clear_auth_lock_after_solver_success(scope)

    assert {path: path.read_bytes() for path in paths} == durable_before
    assert server.RUNTIME.recovery.snapshot() == recovery_before
    assert server.RUNTIME.solver.snapshot() == solver_before
    assert server.RUNTIME.control.snapshot() == pause_before
    scoped = server._solver_scope_runtime_status(scope)
    assert scoped["challenge_id"] is None
    assert scoped["paused"] is False
    assert not Path(server._solver_scope_manual_flag_path(scope)).exists()
    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    assert server._restore_solver_challenge_state() is True
    assert server.RUNTIME.recovery.snapshot().challenge_id == "legacy-id"
    assert server._solver_manual_flag_is_manual_only() is True
    assert server._collection_effectively_paused() is True


@pytest.mark.parametrize("scope", ["seed", "detail", None])
@pytest.mark.parametrize("operator_pause", [False, True])
def test_automated_success_clears_own_compatibility_state(
    monkeypatch, tmp_path, scope, operator_pause
):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    request = {"node_id": "pc2"}
    if scope:
        request["scope"] = scope
    server.RUNTIME.recovery.set_request(request)
    server._begin_solver_challenge(request)
    assert server._mark_solver_manual_required(scope=scope, manual_only=True) is None
    if operator_pause:
        server.RUNTIME.control.set_pause(True, "operator")
    before = server.RUNTIME.recovery.snapshot()

    # Omitting scope must continue to infer it from the active request.
    server._clear_auth_lock_after_solver_success()

    after = server.RUNTIME.recovery.snapshot()
    assert after.challenge_id is None
    assert after.manual_only is False
    assert after.resume_epoch > before.resume_epoch
    assert after.cancel_epoch == before.cancel_epoch
    assert after.completed_request == request
    assert not server._solver_challenge_state_path().exists()
    assert not Path(server._solver_force_unlock_flag_path()).exists()
    assert server._collection_effectively_paused() is operator_pause
    if scope:
        assert server._solver_scope_runtime_status(scope)["paused"] is False
        assert not Path(server._solver_scope_manual_flag_path(scope)).exists()


@pytest.mark.parametrize("entrypoint", ["finalize", "cooldown", "direct"])
@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("legacy_scope", [None, "same"])
@pytest.mark.parametrize("receipt_failure", [False, True])
def test_scoped_completion_preserves_independent_legacy_pause(
    monkeypatch, tmp_path, entrypoint, scope, legacy_scope, receipt_failure
):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_collection_runtime_state_label", lambda: "test")
    request = {"scope": scope, "node_id": "pc2"}
    challenge_id = server._begin_solver_challenge(request)
    assert server._mark_solver_manual_required(scope=scope, manual_only=True) is None
    legacy_request = {"node_id": "legacy-node"}
    if legacy_scope:
        legacy_request["scope"] = scope
    assert server._persist_solver_challenge_state("legacy-id", legacy_request) is None
    server.RUNTIME.recovery.set_challenge("legacy-id", legacy_request)
    assert server._mark_solver_manual_required(manual_only=True) is None
    paths = [
        server._solver_challenge_state_path(),
        Path(server._solver_force_unlock_flag_path()),
    ]
    durable_before = {path: path.read_bytes() for path in paths}
    recovery_before = server.RUNTIME.recovery.snapshot()
    if receipt_failure:
        monkeypatch.setattr(
            server,
            "_remember_auth_completion_confirmation",
            lambda *_: "receipt locked",
        )

    if entrypoint == "finalize":
        result = server._finalize_auth_completion_after_cookie_snapshot(
            "scoped-completion",
            expected_challenge_id=challenge_id,
            completion_request=request,
        )
    elif entrypoint == "cooldown":
        result = server._collection_observer_resume_after_cooldown_payload(
            {**request, "challenge_id": challenge_id, "resume_request_id": "scoped"}
        )
    else:
        result = server._collection_observer_auth_complete_payload(
            {
                **request,
                "challenge_id": challenge_id,
                "completion_id": "scoped-completion",
                "source": "operator",
                "refresh_cookie_snapshot": False,
            }
        )

    assert result["auth_state_confirmed"] is (not receipt_failure)
    assert {path: path.read_bytes() for path in paths} == durable_before
    recovered = server.RUNTIME.recovery.snapshot()
    assert recovered.challenge_id == "legacy-id"
    assert recovered.last_request == legacy_request
    assert recovered.manual_only is True
    assert recovered.required_epoch == recovery_before.required_epoch
    assert recovered.resume_epoch == recovery_before.resume_epoch
    assert server.RUNTIME.control.snapshot().paused is True
    assert server._collection_effectively_paused() is True
    scoped = server._solver_scope_runtime_status(scope)
    if receipt_failure:
        assert "receipt locked" in result["error"]
        assert scoped["challenge_id"] == challenge_id
        assert scoped["paused"] is True
        assert scoped["manual_only"] is True
        return
    assert scoped["challenge_id"] is None
    assert scoped["paused"] is False
    assert scoped["manual_required"] is False
    assert not Path(server._solver_scope_manual_flag_path(scope)).exists()

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    assert server._restore_solver_challenge_state() is True
    assert server.RUNTIME.recovery.snapshot().challenge_id == "legacy-id"
    assert server._solver_manual_flag_is_manual_only() is True
    assert server._collection_effectively_paused() is True
    assert server._clear_solver_manual_required_pause() is None
    assert not any(path.exists() for path in paths)
    assert server._collection_effectively_paused() is False
