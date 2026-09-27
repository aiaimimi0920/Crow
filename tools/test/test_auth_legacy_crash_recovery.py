"""Legacy cleanup must remain retryable across process termination."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.runtime_state import RuntimeState
from tools.test.auth_crash_probe_runner import run_crash_probes


def complete(server, entrypoint):
    if entrypoint in {"finalize", "anonymous"}:
        return server._finalize_auth_completion_after_cookie_snapshot(
            None if entrypoint == "anonymous" else "legacy-crash",
            expected_challenge_id="legacy-id",
            completion_request={"node_id": "legacy-node"},
        )
    if entrypoint == "cooldown":
        return server._collection_observer_resume_after_cooldown_payload(
            {"challenge_id": "legacy-id", "resume_request_id": "legacy-crash"}
        )
    return server._collection_observer_auth_complete_payload(
        {
            "source": "operator",
            "challenge_id": "legacy-id",
            "completion_id": "legacy-crash",
            "refresh_cookie_snapshot": False,
        }
    )


def prepare_legacy(server):
    request = {"node_id": "legacy-node"}
    assert server._persist_solver_challenge_state("legacy-id", request) is None
    server.RUNTIME.recovery.set_challenge("legacy-id", request)
    assert server._mark_solver_manual_required(manual_only=True) is None


def crash_worker(entrypoint, phase, prior_restart="False"):
    from src import server

    server.RUNTIME = RuntimeState()
    server._collection_runtime_state_label = lambda: "test"
    prepare_legacy(server)
    if prior_restart == "True":
        server.RUNTIME = RuntimeState()
        assert server._restore_solver_challenge_state()
    clear = server._clear_solver_manual_required_pause_compat
    remember = server._remember_auth_completion_confirmation
    remove = os.remove
    flag_path = Path(server._solver_force_unlock_flag_path())

    def interrupted_remove(path, *args, **kwargs):
        remove(path, *args, **kwargs)
        if phase == "after_flag" and Path(path) == flag_path:
            os._exit(73)

    def interrupted_clear(scope=None):
        error = clear(scope)
        assert error is None
        if phase == "after_cleanup":
            os._exit(73)
        return error

    def interrupted_remember(completion_id):
        assert remember(completion_id) is None
        os._exit(73)

    os.remove = interrupted_remove
    server._clear_solver_manual_required_pause_compat = interrupted_clear
    server._remember_auth_completion_confirmation = interrupted_remember
    complete(server, entrypoint)
    raise AssertionError("legacy cleanup did not reach the crash boundary")


@pytest.fixture
def startup(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    started = []

    class FakeThread:
        def __init__(self, *, target, daemon):
            assert daemon is True
            self.target = target

        def start(self):
            started.append(self.target)

    monkeypatch.setattr(server, "threading", SimpleNamespace(Thread=FakeThread))
    for name in ("cleanup_orphaned_files", "load_data", "_sample_nas_auth_recovery"):
        monkeypatch.setattr(server, name, lambda: None)
    monkeypatch.setattr(
        server, "DB_REPOSITORY", SimpleNamespace(enabled=False, initialize=lambda: None)
    )
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", SimpleNamespace(enabled=False))
    monkeypatch.setattr(server, "_collection_runtime_state_label", lambda: "test")
    return server, started


@pytest.mark.parametrize("entrypoint", ["finalize", "cooldown", "direct", "anonymous"])
@pytest.mark.parametrize(
    "phase,prior_restart",
    [
        ("after_flag", False),
        ("after_cleanup", False),
        ("after_receipt", False),
        ("after_flag", True),
    ],
)
def test_legacy_process_exit_restores_manual_challenge_and_retry(
    startup, monkeypatch, crash_results, entrypoint, phase, prior_restart
):
    server, started = startup
    child, tmp_path = crash_results[(entrypoint, phase, str(prior_restart))]
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    assert child.returncode == 73, child.stdout + child.stderr

    server.initialize_runtime()

    recovery = server.RUNTIME.recovery.snapshot()
    assert recovery.challenge_id == "legacy-id"
    assert recovery.last_request == {"node_id": "legacy-node"}
    assert server._collection_effectively_paused() is True
    assert server._solver_manual_flag_is_manual_only() is True
    assert recovery.manual_only is True
    assert started == [server.manual_solver_retry_thread]
    confirmation_id = (
        "resume-after-cooldown:legacy-crash"
        if entrypoint == "cooldown"
        else "legacy-crash"
    )
    assert not server._auth_completion_was_confirmed(confirmation_id)
    result = complete(server, entrypoint)
    assert result["auth_state_confirmed"] is True
    if entrypoint != "anonymous":
        assert server._auth_completion_was_confirmed(confirmation_id)
    assert not server._collection_effectively_paused()
    assert not list(tmp_path.glob("auth-cleanup-intent-*.json"))


@pytest.mark.parametrize("entrypoint", ["finalize", "cooldown", "direct"])
def test_restarted_legacy_rollback_preserves_durable_manual_mode(
    startup, monkeypatch, entrypoint
):
    server, _ = startup
    prepare_legacy(server)
    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    assert server._restore_solver_challenge_state()
    monkeypatch.setattr(
        server, "_remember_auth_completion_confirmation", lambda _: "receipt locked"
    )
    assert complete(server, entrypoint)["auth_state_confirmed"] is False
    assert server.RUNTIME.recovery.snapshot().manual_only is True
    assert server._solver_manual_flag_is_manual_only() is True


def pending_cleanup(server):
    from src.auth_cleanup_journal import AuthCleanupIntent
    from src.auth_cleanup_recovery import legacy_cleanup_state

    prepare_legacy(server)
    intent = AuthCleanupIntent(
        server._solver_scope_state_root_path(),
        None,
        legacy_cleanup_state(server.RUNTIME.recovery.snapshot()),
        "legacy-crash",
    )
    assert intent.prepare(read_scope=server._read_solver_scope_state) is None
    with intent.preserve_during_cleanup():
        assert server._clear_solver_manual_required_pause_compat() is None
    return server._solver_scope_state_root_path() / "auth-cleanup-intent-legacy.json"


@pytest.mark.parametrize("entrypoint", ["finalize", "cooldown", "direct"])
@pytest.mark.parametrize("failure", ["prepare", "finish", "partial_cleanup"])
def test_legacy_journal_io_failure_restores_original_challenge(
    startup, tmp_path, monkeypatch, entrypoint, failure
):
    from src import archive_json_io

    server, _ = startup
    prepare_legacy(server)
    intent_path = tmp_path / "auth-cleanup-intent-legacy.json"
    legacy_path = server._solver_challenge_state_path()
    replace, unlink = archive_json_io.os.replace, Path.unlink

    def failed_replace(source, destination):
        if failure == "prepare" and Path(destination) == intent_path:
            raise PermissionError("legacy intent prepare locked")
        return replace(source, destination)

    def failed_unlink(path, *args, **kwargs):
        if (failure == "finish" and path == intent_path) or (
            failure == "partial_cleanup" and path == legacy_path
        ):
            raise PermissionError("legacy cleanup unlink locked")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(archive_json_io.os, "replace", failed_replace)
        fault.setattr(Path, "unlink", failed_unlink)
        result = complete(server, entrypoint)
    assert result["auth_state_confirmed"] is False
    assert "locked" in result["error"]
    assert server.RUNTIME.recovery.snapshot().challenge_id == "legacy-id"
    confirmation_id = (
        "resume-after-cooldown:legacy-crash"
        if entrypoint == "cooldown"
        else "legacy-crash"
    )
    assert not server._auth_completion_was_confirmed(confirmation_id)
    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    server.initialize_runtime()
    assert server.RUNTIME.recovery.snapshot().challenge_id == "legacy-id"
    assert server._solver_manual_flag_is_manual_only() is True
    assert server._collection_effectively_paused() is True
    assert complete(server, entrypoint)["auth_state_confirmed"] is True
    assert not intent_path.exists()


@pytest.mark.parametrize("failure", ["corrupt", "challenge", "flag"])
def test_legacy_restore_failure_blocks_startup_until_retry(
    startup, monkeypatch, failure
):
    server, started = startup
    path = pending_cleanup(server)
    original = path.read_bytes()
    with monkeypatch.context() as fault:
        if failure == "corrupt":
            path.write_text("{", encoding="utf-8")
        else:
            target = (
                "_persist_solver_challenge_state"
                if failure == "challenge"
                else "_write_solver_manual_required_flag"
            )
            fault.setattr(server, target, lambda *args: "legacy restoration locked")
        with pytest.raises(ValueError if failure == "corrupt" else OSError):
            server.initialize_runtime()
    assert not started
    assert not server.RUNTIME.initialized
    assert path.exists()
    if failure == "corrupt":
        path.write_bytes(original)
    server.initialize_runtime()
    assert server.RUNTIME.recovery.snapshot().challenge_id == "legacy-id"
    assert server._solver_manual_flag_is_manual_only() is True
    assert started == [server.manual_solver_retry_thread]


@pytest.mark.parametrize("change", ["metadata", "generation", "scope", "scope_reset"])
def test_legacy_intent_cannot_replace_newer_ownership(startup, change):
    server, _ = startup
    intent_path = pending_cleanup(server)
    if change in {"scope", "scope_reset"}:
        expected_id = server._begin_solver_challenge({"scope": "seed"})
        path = server._solver_scope_state_path("seed")
        if change == "scope_reset":
            assert server._clear_solver_manual_required_pause_compat("seed") is None
            expected_id = None
    else:
        expected_id = "legacy-id" if change == "metadata" else "new-legacy"
        assert (
            server._persist_solver_challenge_state(
                expected_id, {"node_id": "new-owner"}
            )
            is None
        )
        path = server._solver_challenge_state_path()
    before = path.read_bytes() if path.exists() else None
    server.initialize_runtime()
    assert server.RUNTIME.recovery.snapshot().challenge_id == expected_id
    if change == "metadata":
        assert server.RUNTIME.recovery.snapshot().last_request == {
            "node_id": "new-owner"
        }
        assert intent_path.exists()
    else:
        assert not intent_path.exists()
        if change == "scope":
            original = json.loads(before)
            restored = json.loads(path.read_text(encoding="utf-8"))
            # Normal scoped startup republishes only the receipt timestamp.
            original.pop("updated_at_epoch")
            restored.pop("updated_at_epoch")
            assert restored == original
        else:
            assert (path.read_bytes() if path.exists() else None) == before
    if change == "scope":
        assert server._solver_scope_runtime_status("seed")["paused"] is True
    if change == "scope_reset":
        assert server._collection_effectively_paused() is False


@pytest.mark.parametrize("action", ["operator", "manual"])
def test_explicit_global_resume_retires_legacy_intent(startup, action):
    server, _ = startup
    path = pending_cleanup(server)
    if action == "operator":
        assert (
            server._collection_observer_runtime_control_payload("resume")["ok"] is True
        )
    else:
        assert server._clear_solver_manual_required_pause_compat() is None
    assert not path.exists()
    server.initialize_runtime()
    assert server.RUNTIME.recovery.snapshot().challenge_id is None
    assert server._collection_effectively_paused() is False


def test_legacy_retirement_error_keeps_recovery_evidence(startup, monkeypatch):
    server, _ = startup
    path = pending_cleanup(server)
    before = path.read_bytes()
    unlink = Path.unlink

    def failed_unlink(candidate, *args, **kwargs):
        if candidate == path:
            raise PermissionError("legacy intent retirement locked")
        return unlink(candidate, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Path, "unlink", failed_unlink)
        error = server._clear_solver_manual_required_pause_compat()
    assert "legacy intent retirement locked" in error
    assert path.read_bytes() == before
    server.initialize_runtime()
    assert server.RUNTIME.recovery.snapshot().challenge_id == "legacy-id"
    assert server._solver_manual_flag_is_manual_only() is True


@pytest.fixture(scope="module")
def crash_results(tmp_path_factory):
    cases = [
        (entrypoint, phase, str(restart))
        for entrypoint in ("finalize", "cooldown", "direct", "anonymous")
        for phase, restart in (
            ("after_flag", False),
            ("after_cleanup", False),
            ("after_receipt", False),
            ("after_flag", True),
        )
    ]
    return run_crash_probes(
        Path(__file__).resolve(), cases, tmp_path_factory.mktemp("legacy-crashes")
    )


if __name__ == "__main__":
    crash_worker(*sys.argv[1:])
