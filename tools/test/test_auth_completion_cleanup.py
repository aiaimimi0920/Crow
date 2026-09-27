"""Failed scoped cleanup retains a restartable challenge and can be retried."""

import json
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


def request_for(scope):
    target = (
        "https://sf.taobao.com/list/1.htm"
        if scope == "seed"
        else "https://sf-item.taobao.com/sf_item/3001.htm"
    )
    return {"scope": scope, "target_url": target, "node_id": "pc2"}


def complete(server, entrypoint, challenge_id, request):
    if entrypoint == "finalize":
        return server._finalize_auth_completion_after_cookie_snapshot(
            "cleanup-completion",
            expected_challenge_id=challenge_id,
            completion_request=request,
        )
    return server._collection_observer_resume_after_cooldown_payload(
        {
            **request,
            "challenge_id": challenge_id,
            "resume_request_id": "cleanup-completion",
            "source": "pc2_local_solver",
        }
    )


@pytest.mark.parametrize("entrypoint", ["finalize", "cooldown"])
@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("failure", ["legacy", "scoped"])
def test_failed_scoped_cleanup_preserves_challenge_through_restart(
    server_runtime, monkeypatch, entrypoint, scope, failure
):
    server = server_runtime
    other_scope = "detail" if scope == "seed" else "seed"
    request = request_for(scope)
    other_id = server._begin_solver_challenge(request_for(other_scope))
    assert (
        server._mark_solver_manual_required(scope=other_scope, manual_only=True) is None
    )
    challenge_id = server._begin_solver_challenge(request)
    assert server._mark_solver_manual_required(scope=scope, manual_only=True) is None
    path = server._solver_scope_state_path(scope)
    other_path = server._solver_scope_state_path(other_scope)
    original = json.loads(path.read_text(encoding="utf-8"))
    other_original = other_path.read_bytes()
    failing_path = (
        server._solver_challenge_state_path() if failure == "legacy" else path
    )
    unlink = Path.unlink
    confirmation_id = (
        "cleanup-completion"
        if entrypoint == "finalize"
        else "resume-after-cooldown:cleanup-completion"
    )

    def fail_unlink(candidate, *args, **kwargs):
        if candidate == failing_path:
            raise PermissionError("challenge receipt locked")
        return unlink(candidate, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Path, "unlink", fail_unlink)
        result = complete(server, entrypoint, challenge_id, request)

    assert result["auth_state_confirmed"] is False
    assert "challenge receipt locked" in result["error"]
    status = server._solver_scope_runtime_status(scope)
    assert status["challenge_id"] == challenge_id
    assert status["paused"] is True
    assert status["manual_required"] is True
    assert status["manual_only"] is True
    persisted = json.loads(path.read_text(encoding="utf-8"))
    # Cooldown failure refreshes the pause receipt's publication timestamp.
    persisted.pop("updated_at_epoch")
    original.pop("updated_at_epoch")
    assert persisted == original
    assert other_path.read_bytes() == other_original
    recovery = server.RUNTIME.recovery.snapshot()
    assert recovery.challenge_id == challenge_id
    assert recovery.resume_epoch == 0
    assert recovery.completed_at == 0
    assert not server._auth_completion_was_confirmed(confirmation_id)

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    server._restore_solver_challenge_state()
    assert server._restore_solver_scope_states() is True
    restored = server._solver_scope_runtime_status(scope)
    assert restored["challenge_id"] == challenge_id
    assert restored["paused"] is True
    assert restored["manual_required"] is True
    assert restored["manual_only"] is True
    other_restored = other_path.read_bytes()

    retried = complete(server, entrypoint, challenge_id, request)

    assert retried["auth_state_confirmed"] is True
    assert server._auth_completion_was_confirmed(confirmation_id)
    assert server._solver_scope_runtime_status(scope)["paused"] is False
    other_status = server._solver_scope_runtime_status(other_scope)
    assert other_status["challenge_id"] == other_id
    assert other_status["paused"] is True
    assert other_path.read_bytes() == other_restored


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("restore_failure", [False, True])
@pytest.mark.parametrize("entrypoint", ["cooldown", "finalize"])
def test_failed_confirmation_retains_restartable_challenge(
    server_runtime, monkeypatch, scope, restore_failure, entrypoint
):
    from src import archive_json_io

    server = server_runtime
    other_scope = "detail" if scope == "seed" else "seed"
    other_id = server._begin_solver_challenge(request_for(other_scope))
    assert server._mark_solver_manual_required(scope=other_scope) is None
    request = request_for(scope)
    challenge_id = server._begin_solver_challenge(request)
    assert server._mark_solver_manual_required(scope=scope, manual_only=True) is None
    other_path = server._solver_scope_state_path(other_scope)
    other_original = other_path.read_bytes()
    confirmation_path = server._auth_completion_confirmation_path()
    confirmation_id = (
        "cleanup-completion"
        if entrypoint == "finalize"
        else "resume-after-cooldown:cleanup-completion"
    )
    scope_path = server._solver_scope_state_path(scope)
    replace = archive_json_io.os.replace
    confirmation_failed = False

    def fail_confirmation(source, destination):
        nonlocal confirmation_failed
        if Path(destination) == confirmation_path:
            confirmation_failed = True
            raise PermissionError("confirmation publication locked")
        if restore_failure and confirmation_failed and Path(destination) == scope_path:
            raise PermissionError("challenge rollback locked")
        return replace(source, destination)

    with monkeypatch.context() as fault:
        fault.setattr(archive_json_io.os, "replace", fail_confirmation)
        result = complete(server, entrypoint, challenge_id, request)

    assert result["auth_state_confirmed"] is False
    assert "confirmation publication locked" in result["error"]
    if restore_failure:
        assert "challenge rollback locked" in result["recovery_error"]
        assert server._collection_scope_effectively_paused(scope) is True
        assert other_path.read_bytes() == other_original
        monkeypatch.setattr(server, "RUNTIME", RuntimeState())
        server._restore_solver_challenge_state()
        server._restore_solver_scope_states()
        assert server._collection_scope_effectively_paused(scope) is True
        assert not server._auth_completion_was_confirmed(confirmation_id)
        return
    assert "recovery_error" not in result
    status = server._solver_scope_runtime_status(scope)
    assert status["challenge_id"] == challenge_id
    assert status["paused"] is True
    assert status["manual_required"] is True
    assert status["manual_only"] is True
    assert server.RUNTIME.recovery.snapshot().resume_epoch == 0
    assert not server._auth_completion_was_confirmed(confirmation_id)
    assert other_path.read_bytes() == other_original

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    server._restore_solver_challenge_state()
    assert server._restore_solver_scope_states() is True
    restored = server._solver_scope_runtime_status(scope)
    assert restored["challenge_id"] == challenge_id
    assert restored["paused"] is True
    assert restored["manual_only"] is True
    assert restored["last_request"] == request
    other_restored = other_path.read_bytes()

    retried = complete(server, entrypoint, challenge_id, request)

    assert retried["auth_state_confirmed"] is True
    assert server._auth_completion_was_confirmed(confirmation_id)
    assert server._solver_scope_runtime_status(scope)["paused"] is False
    assert server._solver_scope_runtime_status(other_scope)["challenge_id"] == other_id
    assert server._solver_scope_runtime_status(other_scope)["paused"] is True
    assert other_path.read_bytes() == other_restored


@pytest.mark.parametrize("scope", ["seed", "detail"])
def test_scoped_completion_preserves_other_scopes_compatibility_receipt(
    server_runtime, scope
):
    server = server_runtime
    other_scope = "detail" if scope == "seed" else "seed"
    request = request_for(scope)
    challenge_id = server._begin_solver_challenge(request)
    assert server._mark_solver_manual_required(scope=scope, manual_only=True) is None
    other_id = server._begin_solver_challenge(request_for(other_scope))
    assert (
        server._mark_solver_manual_required(scope=other_scope, manual_only=True) is None
    )
    legacy = server._solver_challenge_state_path()
    other_path = server._solver_scope_state_path(other_scope)
    original, other_original = legacy.read_bytes(), other_path.read_bytes()

    result = complete(server, "finalize", challenge_id, request)

    assert result["auth_state_confirmed"] is True
    assert server._solver_scope_runtime_status(scope)["paused"] is False
    assert server.RUNTIME.recovery.snapshot().challenge_id == other_id
    assert legacy.read_bytes() == original
    assert other_path.read_bytes() == other_original
