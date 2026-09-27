"""Interrupted auth cleanup restores its original challenge before startup."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.runtime_state import RuntimeState


def complete(server, entrypoint, challenge_id, request):
    if entrypoint in {"finalize", "anonymous"}:
        return server._finalize_auth_completion_after_cookie_snapshot(
            None if entrypoint == "anonymous" else "crash-completion",
            expected_challenge_id=challenge_id,
            completion_request=request,
        )
    if entrypoint == "cooldown":
        return server._collection_observer_resume_after_cooldown_payload(
            {
                **request,
                "challenge_id": challenge_id,
                "resume_request_id": "crash-completion",
                "source": "pc2_local_solver",
            }
        )
    return server._collection_observer_auth_complete_payload(
        {
            **request,
            "challenge_id": challenge_id,
            "completion_id": "crash-completion",
            "source": "operator",
            "refresh_cookie_snapshot": False,
        }
    )


def crash_worker(entrypoint, scope, phase):
    from src import server

    server.RUNTIME = RuntimeState()
    server._collection_runtime_state_label = lambda: "test"
    server._schedule_auth_cookie_snapshot_refresh = lambda *args, **kwargs: {
        "status": "skipped"
    }
    request = {"scope": scope, "node_id": "pc2"}
    challenge_id = server._begin_solver_challenge(request)
    assert server._mark_solver_manual_required(scope=scope, manual_only=True) is None
    root = Path(os.environ["FAPAI_SOLVER_STATE_DIR"])
    (root / "expected.json").write_text(
        json.dumps({"challenge_id": challenge_id, "request": request}),
        encoding="utf-8",
    )
    clear = server._clear_solver_manual_required_pause_compat
    remember = server._remember_auth_completion_confirmation

    def interrupted_clear(selected_scope=None):
        error = clear(selected_scope)
        assert error is None
        if phase == "after_cleanup":
            os._exit(73)
        return error

    def interrupted_remember(completion_id):
        error = remember(completion_id)
        assert error is None
        os._exit(73)

    server._clear_solver_manual_required_pause_compat = interrupted_clear
    server._remember_auth_completion_confirmation = interrupted_remember
    complete(server, entrypoint, challenge_id, request)
    raise AssertionError("auth cleanup did not reach the crash boundary")


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
    monkeypatch.setattr(
        server,
        "_schedule_auth_cookie_snapshot_refresh",
        lambda *args, **kwargs: {"status": "skipped"},
    )
    return server, started


@pytest.mark.parametrize("entrypoint", ["finalize", "cooldown", "direct", "anonymous"])
@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("phase", ["after_cleanup", "after_receipt"])
def test_process_exit_restores_challenge_and_allows_same_request_retry(
    startup, tmp_path, entrypoint, scope, phase
):
    server, started = startup
    child = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), entrypoint, scope, phase],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == 73, child.stdout + child.stderr
    expected = json.loads((tmp_path / "expected.json").read_text(encoding="utf-8"))

    server.initialize_runtime()

    restored = server._solver_scope_runtime_status(scope)
    assert restored["challenge_id"] == expected["challenge_id"]
    assert restored["paused"] is True
    assert restored["manual_required"] is True
    assert restored["manual_only"] is True
    assert restored["last_request"] == expected["request"]
    assert started == [server.manual_solver_retry_thread]
    confirmation_id = (
        "resume-after-cooldown:crash-completion"
        if entrypoint == "cooldown"
        else "crash-completion"
    )
    assert not server._auth_completion_was_confirmed(confirmation_id)

    result = complete(server, entrypoint, expected["challenge_id"], expected["request"])

    assert result["auth_state_confirmed"] is True
    if entrypoint != "anonymous":
        assert server._auth_completion_was_confirmed(confirmation_id)
    assert server._solver_scope_runtime_status(scope)["paused"] is False
    assert not list(tmp_path.glob("auth-cleanup-intent-*.json"))


@pytest.mark.parametrize("entrypoint", ["finalize", "cooldown", "direct"])
@pytest.mark.parametrize("failure", ["prepare", "finish"])
def test_journal_io_failure_keeps_original_challenge_retryable(
    startup, tmp_path, monkeypatch, entrypoint, failure
):
    from src import archive_json_io

    server, _ = startup
    request = {"scope": "seed", "node_id": "pc2"}
    challenge_id = server._begin_solver_challenge(request)
    assert server._mark_solver_manual_required(scope="seed", manual_only=True) is None
    intent_path = tmp_path / "auth-cleanup-intent-seed.json"
    replace, unlink = archive_json_io.os.replace, Path.unlink

    def fail_replace(source, destination):
        if Path(destination) == intent_path:
            raise PermissionError("intent prepare locked")
        return replace(source, destination)

    def fail_unlink(path, *args, **kwargs):
        if path == intent_path:
            raise PermissionError("intent finish locked")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        if failure == "prepare":
            fault.setattr(archive_json_io.os, "replace", fail_replace)
        else:
            fault.setattr(Path, "unlink", fail_unlink)
        result = complete(server, entrypoint, challenge_id, request)

    assert result["auth_state_confirmed"] is False
    assert f"intent {failure} locked" in result["error"]
    state = server._solver_scope_runtime_status("seed")
    assert state["challenge_id"] == challenge_id
    assert state["paused"] is True
    assert state["manual_only"] is True
    confirmation_id = (
        "resume-after-cooldown:crash-completion"
        if entrypoint == "cooldown"
        else "crash-completion"
    )
    assert not server._auth_completion_was_confirmed(confirmation_id)
    assert complete(server, entrypoint, challenge_id, request)["auth_state_confirmed"]
    assert server._auth_completion_was_confirmed(confirmation_id)
    assert not intent_path.exists()


def test_corrupt_intent_blocks_startup_before_workers_and_can_retry(startup, tmp_path):
    server, started = startup
    path = tmp_path / "auth-cleanup-intent-seed.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError):
        server.initialize_runtime()

    assert started == []
    assert server.RUNTIME.initialized is False
    assert path.read_text(encoding="utf-8") == "{"
    path.unlink()
    server.initialize_runtime()
    assert started == [server.manual_solver_retry_thread]


@pytest.mark.parametrize("change", ["generation", "metadata"])
def test_pending_intent_cannot_replace_a_newer_challenge(startup, tmp_path, change):
    from src.auth_cleanup_journal import AuthCleanupIntent

    server, _ = startup
    request = {"scope": "seed", "node_id": "pc2"}
    old_id = server._begin_solver_challenge(request)
    original = server._read_solver_scope_state("seed")
    intent = AuthCleanupIntent(tmp_path, "seed", original, "old-completion")
    assert intent.prepare() is None
    if change == "generation":
        with intent.preserve_during_cleanup():
            assert server._clear_solver_challenge_state("seed") is None
    request = {**request, "node_id": "new-owner"}
    new_id = server._begin_solver_challenge(request)
    assert (new_id != old_id) is (change == "generation")

    server.initialize_runtime()

    assert server._solver_scope_runtime_status("seed")["challenge_id"] == new_id
    assert server._solver_scope_runtime_status("seed")["last_request"] == request
    assert (tmp_path / "auth-cleanup-intent-seed.json").exists() is (
        change == "metadata"
    )


def test_failed_journal_restoration_blocks_workers_until_retry(
    startup, tmp_path, monkeypatch
):
    from src.auth_cleanup_journal import AuthCleanupIntent

    server, started = startup
    challenge_id = server._begin_solver_challenge({"scope": "seed"})
    intent = AuthCleanupIntent(
        tmp_path, "seed", server._read_solver_scope_state("seed"), "interrupted"
    )
    assert intent.prepare() is None
    with intent.preserve_during_cleanup():
        assert server._clear_solver_challenge_state("seed") is None
    with monkeypatch.context() as fault:
        fault.setattr(
            server, "_persist_solver_scope_state", lambda *args: "restore locked"
        )
        with pytest.raises(OSError, match="restore locked"):
            server.initialize_runtime()
    assert not started
    assert server.RUNTIME.initialized is False
    assert (tmp_path / "auth-cleanup-intent-seed.json").exists()
    server.initialize_runtime()
    assert server._solver_scope_runtime_status("seed")["challenge_id"] == challenge_id
    assert server._solver_scope_runtime_status("seed")["paused"] is True


@pytest.mark.parametrize("action", ["operator", "manual"])
def test_explicit_resume_retires_intent_without_resurrection(startup, tmp_path, action):
    from src.auth_cleanup_journal import AuthCleanupIntent

    server, _ = startup
    server._begin_solver_challenge({"scope": "seed", "node_id": "pc2"})
    assert server._mark_solver_manual_required(scope="seed") is None
    intent = AuthCleanupIntent(
        tmp_path, "seed", server._read_solver_scope_state("seed"), "interrupted"
    )
    assert intent.prepare() is None
    if action == "operator":
        assert server._collection_observer_runtime_control_payload("resume")["ok"]
    else:
        assert server._clear_solver_manual_required_pause_compat("seed") is None

    server.initialize_runtime()

    assert server._solver_scope_runtime_status("seed")["challenge_id"] is None
    assert server._collection_scope_effectively_paused("seed") is False
    assert not (tmp_path / "auth-cleanup-intent-seed.json").exists()


def test_failed_intent_retirement_keeps_challenge(startup, tmp_path, monkeypatch):
    from src.auth_cleanup_journal import AuthCleanupIntent

    server, _ = startup
    challenge_id = server._begin_solver_challenge({"scope": "seed"})
    intent = AuthCleanupIntent(
        tmp_path, "seed", server._read_solver_scope_state("seed"), "interrupted"
    )
    assert intent.prepare() is None
    path = tmp_path / "auth-cleanup-intent-seed.json"
    original = server._solver_scope_state_path("seed").read_bytes()
    unlink = Path.unlink

    def fail_unlink(candidate, *args, **kwargs):
        if candidate == path:
            raise PermissionError("intent retirement locked")
        return unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    assert "intent retirement locked" in server._clear_solver_challenge_state("seed")
    assert server._solver_scope_state_path("seed").read_bytes() == original
    assert server._solver_scope_runtime_status("seed")["challenge_id"] == challenge_id


if __name__ == "__main__":
    crash_worker(*sys.argv[1:])
