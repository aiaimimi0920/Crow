"""Legacy completion must retain retry identity and respect scoped challenges."""

from pathlib import Path

import pytest

from src.runtime_state import RuntimeState


@pytest.fixture
def server_runtime(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_collection_runtime_state_label", lambda: "test")
    return server


def prepare_legacy(server):
    request = {"node_id": "legacy-node"}
    assert server._persist_solver_challenge_state("legacy-id", request) is None
    server.RUNTIME.recovery.set_challenge("legacy-id", request)
    assert server._mark_solver_manual_required(manual_only=True) is None
    return request


def complete(server, entrypoint, request):
    if entrypoint == "finalize":
        return server._finalize_auth_completion_after_cookie_snapshot(
            "legacy-completion",
            expected_challenge_id="legacy-id",
            completion_request=request,
        )
    if entrypoint == "cooldown":
        return server._collection_observer_resume_after_cooldown_payload(
            {
                **request,
                "resume_request_id": "legacy-completion",
                "challenge_id": "legacy-id",
            }
        )
    return server._collection_observer_auth_complete_payload(
        {
            **request,
            "source": "operator",
            "completion_id": "legacy-completion",
            "challenge_id": "legacy-id",
            "refresh_cookie_snapshot": False,
        }
    )


@pytest.mark.parametrize("entrypoint", ["finalize", "cooldown", "direct"])
@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("scoped_state", ["active", "pending_cleanup"])
def test_ambiguous_legacy_completion_preserves_active_scoped_challenge(
    server_runtime, entrypoint, scope, scoped_state
):
    from src.auth_cleanup_journal import AuthCleanupIntent, recover_pending_cleanups

    server = server_runtime
    scoped_id = server._begin_solver_challenge({"scope": scope, "node_id": "pc2"})
    assert server._mark_solver_manual_required(scope=scope, manual_only=True) is None
    scoped_path = server._solver_scope_state_path(scope)
    if scoped_state == "pending_cleanup":
        intent = AuthCleanupIntent(
            server._solver_scope_state_root_path(),
            scope,
            server._read_solver_scope_state(scope),
            "pending-scoped-completion",
        )
        assert intent.prepare() is None
        with intent.preserve_during_cleanup():
            assert server._clear_solver_challenge_state(scope) is None
        scoped_path = scoped_path.parent / f"auth-cleanup-intent-{scope}.json"
    request = prepare_legacy(server)
    paths = [
        scoped_path,
        server._solver_challenge_state_path(),
        Path(server._solver_scope_manual_flag_path(scope)),
        Path(server._solver_force_unlock_flag_path()),
    ]
    before = {path: path.read_bytes() for path in paths}

    result = complete(server, entrypoint, request)

    assert result["auth_state_confirmed"] is False
    assert "active scoped challenge" in result["error"]
    assert {path: path.read_bytes() for path in paths} == before
    assert server.RUNTIME.recovery.snapshot().challenge_id == "legacy-id"
    if scoped_state == "pending_cleanup":
        with server.RUNTIME.lock:
            assert (
                recover_pending_cleanups(
                    scoped_path.parent,
                    read_scope=server._read_solver_scope_state,
                    persist_scope=server._persist_solver_scope_state,
                )
                == 1
            )
    status = server._solver_scope_runtime_status(scope)
    assert status["challenge_id"] == scoped_id
    assert status["paused"] is True
    assert status["manual_only"] is True


@pytest.mark.parametrize("entrypoint", ["finalize", "cooldown", "direct"])
@pytest.mark.parametrize("restore_failure", [None, "challenge", "flag"])
def test_legacy_confirmation_failure_retains_original_retry_identity(
    server_runtime, monkeypatch, entrypoint, restore_failure
):
    from src import archive_json_io

    server = server_runtime
    request = prepare_legacy(server)
    before = server.RUNTIME.recovery.snapshot()
    confirmation_path = server._auth_completion_confirmation_path()
    legacy_path = server._solver_challenge_state_path()
    replace = archive_json_io.os.replace
    confirmation_failed = False

    def fail_publication(source, destination):
        nonlocal confirmation_failed
        if Path(destination) == confirmation_path:
            confirmation_failed = True
            raise PermissionError("confirmation publication locked")
        if (
            restore_failure == "challenge"
            and confirmation_failed
            and Path(destination) == legacy_path
        ):
            raise PermissionError("legacy rollback locked")
        return replace(source, destination)

    with monkeypatch.context() as fault:
        fault.setattr(archive_json_io.os, "replace", fail_publication)
        if restore_failure == "flag":
            fault.setattr(
                server,
                "_write_solver_manual_required_flag",
                lambda *_, **_kwargs: "flag locked",
            )
        result = complete(server, entrypoint, request)

    assert result["auth_state_confirmed"] is False
    assert "confirmation publication locked" in result["error"]
    recovery = server.RUNTIME.recovery.snapshot()
    assert recovery.challenge_id == "legacy-id"
    assert recovery.last_request == request
    assert recovery.resume_epoch == before.resume_epoch
    assert recovery.required_epoch == before.required_epoch
    assert recovery.manual_only is True
    confirmation_id = (
        "resume-after-cooldown:legacy-completion"
        if entrypoint == "cooldown"
        else "legacy-completion"
    )
    assert not server._auth_completion_was_confirmed(confirmation_id)
    if restore_failure:
        expected = (
            "legacy rollback locked"
            if restore_failure == "challenge"
            else "flag locked"
        )
        assert expected in result["recovery_error"]
    else:
        assert "recovery_error" not in result

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    restored = server._restore_solver_challenge_state()
    assert server._collection_effectively_paused() is True
    if restore_failure == "challenge":
        assert restored is False
        assert Path(server._solver_force_unlock_flag_path()).exists()
        return
    assert restored is True
    assert server.RUNTIME.recovery.snapshot().challenge_id == "legacy-id"
    if restore_failure is None:
        assert server._solver_manual_flag_is_manual_only() is True
    retried = complete(server, entrypoint, request)
    assert retried["auth_state_confirmed"] is True
    assert server._auth_completion_was_confirmed(confirmation_id)
