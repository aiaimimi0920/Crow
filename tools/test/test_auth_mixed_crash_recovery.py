"""Scoped cleanup crashes must preserve an independent legacy manual pause."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.runtime_state import RuntimeState


def complete(server, entrypoint, challenge_id, request):
    if entrypoint == "finalize":
        return server._finalize_auth_completion_after_cookie_snapshot(
            "mixed-crash",
            expected_challenge_id=challenge_id,
            completion_request=request,
        )
    payload = {**request, "challenge_id": challenge_id}
    if entrypoint == "cooldown":
        return server._collection_observer_resume_after_cooldown_payload(
            {**payload, "resume_request_id": "mixed-crash"}
        )
    return server._collection_observer_auth_complete_payload(
        {
            **payload,
            "completion_id": "mixed-crash",
            "source": "operator",
            "refresh_cookie_snapshot": False,
        }
    )


def crash_worker(entrypoint, scope, phase):
    from src import server

    server.RUNTIME = RuntimeState()
    server._collection_runtime_state_label = lambda: "test"
    request = {"scope": scope, "node_id": "pc2"}
    challenge_id = server._begin_solver_challenge(request)
    assert server._mark_solver_manual_required(scope=scope, manual_only=True) is None
    legacy_request = {"node_id": "legacy-node"}
    if scope == "detail":
        legacy_request["scope"] = scope
    assert server._persist_solver_challenge_state("legacy-id", legacy_request) is None
    server.RUNTIME.recovery.set_challenge("legacy-id", legacy_request)
    assert server._mark_solver_manual_required(manual_only=True) is None
    paths = [
        server._solver_challenge_state_path(),
        Path(server._solver_force_unlock_flag_path()),
    ]
    root = Path(os.environ["FAPAI_SOLVER_STATE_DIR"])
    (root / "expected.json").write_text(
        json.dumps(
            {
                "challenge_id": challenge_id,
                "request": request,
                "legacy_request": legacy_request,
                "required_epoch": server.RUNTIME.recovery.snapshot().required_epoch,
                "files": {
                    path.name: path.read_text(encoding="utf-8") for path in paths
                },
            }
        ),
        encoding="utf-8",
    )
    unlink = Path.unlink
    clear = server._clear_solver_manual_required_pause_compat
    remember = server._remember_auth_completion_confirmation
    scoped_flag = Path(server._solver_scope_manual_flag_path(scope))

    def interrupted_unlink(path, *args, **kwargs):
        result = unlink(path, *args, **kwargs)
        if phase == "after_flag" and path == scoped_flag:
            os._exit(73)
        return result

    def interrupted_clear(selected_scope=None):
        error = clear(selected_scope)
        assert error is None
        if phase == "after_cleanup":
            os._exit(73)
        return error

    def interrupted_remember(completion_id):
        assert remember(completion_id) is None
        os._exit(73)

    Path.unlink = interrupted_unlink
    server._clear_solver_manual_required_pause_compat = interrupted_clear
    server._remember_auth_completion_confirmation = interrupted_remember
    complete(server, entrypoint, challenge_id, request)
    raise AssertionError("mixed cleanup did not reach crash boundary")


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


@pytest.mark.parametrize("entrypoint", ["finalize", "cooldown", "direct"])
@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("phase", ["after_flag", "after_cleanup", "after_receipt"])
def test_mixed_crash_restores_both_owners_before_workers(
    startup, tmp_path, monkeypatch, entrypoint, scope, phase
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
    for _ in range(2):
        monkeypatch.setattr(server, "RUNTIME", RuntimeState())
        started.clear()
        server.initialize_runtime()
        recovery = server.RUNTIME.recovery.snapshot()
        assert recovery.challenge_id == "legacy-id"
        assert recovery.last_request == expected["legacy_request"]
        assert recovery.manual_only is True
        assert recovery.required_epoch == expected["required_epoch"]
        assert server._collection_effectively_paused() is True
        scoped = server._solver_scope_runtime_status(scope)
        assert scoped["challenge_id"] == expected["challenge_id"]
        assert scoped["manual_only"] is True
        assert scoped["paused"] is True
        assert started == [server.manual_solver_retry_thread]
        for name, contents in expected["files"].items():
            assert (tmp_path / name).read_bytes() == contents.encode("utf-8")

    confirmation_id = (
        "resume-after-cooldown:mixed-crash"
        if entrypoint == "cooldown"
        else "mixed-crash"
    )
    assert not server._auth_completion_was_confirmed(confirmation_id)
    result = complete(server, entrypoint, expected["challenge_id"], expected["request"])
    assert result["auth_state_confirmed"] is True
    assert server._auth_completion_was_confirmed(confirmation_id)
    assert server._solver_scope_runtime_status(scope)["paused"] is False
    assert server.RUNTIME.recovery.snapshot().challenge_id == "legacy-id"
    assert server.RUNTIME.recovery.snapshot().manual_only is True
    assert server._collection_effectively_paused() is True
    for name, contents in expected["files"].items():
        assert (tmp_path / name).read_bytes() == contents.encode("utf-8")
    assert not list(tmp_path.glob("auth-cleanup-intent-*.json"))
    assert server._clear_solver_manual_required_pause() is None
    assert not server._collection_effectively_paused()


@pytest.mark.parametrize(
    "flag_kind", ["manual_only", "retryable", "other_owner", "opaque", "invalid_epoch"]
)
def test_startup_restores_only_matching_valid_manual_metadata(startup, flag_kind):
    server, started = startup
    request = {"node_id": "legacy-node"}
    assert server._persist_solver_challenge_state("legacy-id", request) is None
    server.RUNTIME.recovery.set_challenge("legacy-id", request)
    assert (
        server._mark_solver_manual_required(manual_only=flag_kind != "retryable")
        is None
    )
    flag_path = Path(server._solver_force_unlock_flag_path())
    payload = json.loads(flag_path.read_text(encoding="utf-8"))
    if flag_kind == "other_owner":
        payload["last_request"] = {"node_id": "different-node"}
    if flag_kind == "invalid_epoch":
        payload["created_at_epoch"] = "invalid"
    flag_path.write_text(
        "manual lock" if flag_kind == "opaque" else json.dumps(payload),
        encoding="utf-8",
    )
    before = flag_path.read_bytes()
    server.RUNTIME = RuntimeState()

    server.initialize_runtime()

    recovery = server.RUNTIME.recovery.snapshot()
    assert recovery.challenge_id == "legacy-id"
    assert recovery.last_request == request
    assert recovery.manual_only is (flag_kind == "manual_only")
    assert recovery.required_epoch == (
        payload["created_at_epoch"] if flag_kind in {"manual_only", "retryable"} else 0
    )
    assert server._collection_effectively_paused() is True
    assert started == [server.manual_solver_retry_thread]
    assert flag_path.read_bytes() == before


if __name__ == "__main__":
    crash_worker(*sys.argv[1:])
