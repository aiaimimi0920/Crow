"""Scoped challenge persistence and recovery with explicit runtime ownership."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src import solver_scope_runtime
from src.runtime_state import RuntimeState
from src.solver_scope_runtime import SolverScopeRuntime

SEED_URL = "https://sf.taobao.com/list/50025969__2.htm"


def observe_contention(runtime, monkeypatch):
    """Signal a failed real acquisition while retaining the shared RLock."""
    lock = runtime.lock
    contended = threading.Event()

    class ObservedLock:
        def __enter__(self):
            if not lock.acquire(blocking=False):
                contended.set()
                lock.acquire()
            return self

        def __exit__(self, *_args):
            lock.release()

    monkeypatch.setattr(runtime, "lock", ObservedLock())
    return contended


@pytest.fixture
def scopes(monkeypatch, tmp_path):
    monkeypatch.delenv("FAPAI_SOLVER_STATE_DIR", raising=False)
    return SolverScopeRuntime(
        RuntimeState(), tmp_path, lambda: tmp_path / "legacy.json", 900.0
    )


def receipt(challenge_id):
    return {
        "challenge_id": challenge_id,
        "first_seen_epoch": 10.0,
        "paused": True,
        "last_request": {"target_url": SEED_URL},
    }


def test_scope_receipt_survives_reload_without_sharing_runtime(scopes):
    assert scopes.persist("seed", receipt("seed-active")) is None
    reloaded = SolverScopeRuntime(
        RuntimeState(), scopes.data_dir, scopes.legacy_state_path, 900.0
    )
    status = reloaded.status("seed", now=920.0)
    assert status["challenge_id"] == "seed-active"
    assert status["force_reset_required"] is True
    assert status["challenge_age_seconds"] == 910.0
    status["last_request"]["target_url"] = "changed"
    assert reloaded.read("seed")["last_request"] == {"target_url": SEED_URL}
    reloaded.runtime.control.set_pause(True, "operator")
    assert scopes.runtime.control.snapshot().paused is False


def test_failed_scope_publication_preserves_previous_receipt_and_cache(
    scopes, monkeypatch
):
    assert scopes.persist("seed", receipt("original")) is None
    path = scopes.state_path("seed")
    original = path.read_bytes()

    def fail_replace(*_args):
        raise OSError("publication failed")

    monkeypatch.setattr(solver_scope_runtime.os, "replace", fail_replace)
    assert "publication failed" in scopes.persist("seed", receipt("replacement"))
    assert path.read_bytes() == original
    assert scopes.runtime.control.scope_snapshot("seed")["challenge_id"] == "original"


def test_scope_publication_and_cache_update_are_one_transaction(scopes, monkeypatch):
    contended = observe_contention(scopes.runtime, monkeypatch)
    first_replacing, release_first = threading.Event(), threading.Event()
    second_started, second_finished = threading.Event(), threading.Event()
    replace = solver_scope_runtime.os.replace
    receipt_path = scopes.state_path("seed")
    replacements = []

    def controlled_replace(source, destination):
        if Path(destination) != receipt_path:
            return replace(source, destination)
        replacements.append(None)
        if len(replacements) == 1:
            first_replacing.set()
            assert release_first.wait(5)
        return replace(source, destination)

    def second_write():
        second_started.set()
        try:
            return scopes.persist("seed", receipt("second"))
        finally:
            second_finished.set()

    monkeypatch.setattr(solver_scope_runtime.os, "replace", controlled_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(scopes.persist, "seed", receipt("first"))
        try:
            assert first_replacing.wait(5)
            second = pool.submit(second_write)
            assert second_started.wait(5)
            assert contended.wait(5)
            completed_before_publication = second_finished.is_set()
        finally:
            release_first.set()
        results = first.result(timeout=5), second.result(timeout=5)

    assert results == (None, None)
    assert completed_before_publication is False
    durable = json.loads(scopes.state_path("seed").read_text(encoding="utf-8"))
    assert durable["challenge_id"] == "second"
    assert scopes.runtime.control.scope_snapshot("seed")["challenge_id"] == "second"


def test_inactive_receipt_read_cannot_clear_a_newer_challenge(scopes, monkeypatch):
    contended = observe_contention(scopes.runtime, monkeypatch)
    assert scopes.persist("seed", {**receipt("old"), "challenge_id": None}) is None
    receipt_path = scopes.state_path("seed")
    reader_loaded, release_reader = threading.Event(), threading.Event()
    writer_started, writer_finished = threading.Event(), threading.Event()
    read_text = Path.read_text

    def controlled_read(path, *args, **kwargs):
        content = read_text(path, *args, **kwargs)
        if path == receipt_path:
            reader_loaded.set()
            assert release_reader.wait(5)
        return content

    def write_active():
        writer_started.set()
        try:
            return scopes.persist("seed", receipt("new"))
        finally:
            writer_finished.set()

    monkeypatch.setattr(Path, "read_text", controlled_read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(scopes.read, "seed")
        try:
            assert reader_loaded.wait(5)
            writer = pool.submit(write_active)
            assert writer_started.wait(5)
            assert contended.wait(5)
            completed_before_read = writer_finished.is_set()
        finally:
            release_reader.set()
        assert reader.result(timeout=5)["challenge_id"] is None
        assert writer.result(timeout=5) is None

    assert scopes.runtime.control.scope_snapshot("seed")["challenge_id"] == "new"
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["challenge_id"] == "new"
    assert completed_before_read is False


@pytest.fixture
def server_runtime(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    return server


def test_force_reset_records_scoped_report_grace(server_runtime, monkeypatch):
    server = server_runtime
    request = {
        "node_id": "pc2",
        "cdp_endpoint": "http://pc2.example:9224",
        "target_url": SEED_URL,
    }
    monkeypatch.setattr(server, "CHALLENGE_FORCE_RESET_SECONDS", 900.0)
    state = {
        **receipt("seed-stuck"),
        "first_seen_epoch": time.time() - 901.0,
        "last_request": request,
    }
    assert server._persist_solver_scope_state("seed", state) is None
    flag = Path(server._solver_scope_manual_flag_path("seed"))
    flag.write_text("manual", encoding="utf-8")
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", dict)
    remembered = []
    monkeypatch.setattr(
        server,
        "_remember_solver_force_reset_recovery",
        lambda scope, payload: remembered.append((scope, dict(payload))),
    )

    result = server._force_reset_solver_scope("seed", "seed-stuck")

    assert result["force_reset"] is True
    assert (
        result["report_grace_seconds"] == server.SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS
    )
    assert remembered == [("seed", request)]
    assert not flag.exists()
    assert server._solver_scope_runtime_status("seed")["paused"] is False


def test_manual_only_status_survives_restart_from_persisted_flag(server_runtime):
    server = server_runtime
    flag_path = Path(server._solver_force_unlock_flag_path())
    flag_path.write_text(
        json.dumps(
            {
                "manual_only": True,
                "last_request": {
                    "node_id": "pc2",
                    "cdp_endpoint": "http://pc2.example:9224",
                    "target_url": "https://sf-item.taobao.com/sf_item/3001.htm",
                },
            }
        ),
        encoding="utf-8",
    )

    status = server._captcha_solver_runtime_status()

    assert status["manual_required"] is True
    assert status["manual_only"] is True
    assert status["manual_retry_enabled"] is False
    assert status["last_request"]["node_id"] == "pc2"
    assert status["last_request"]["cdp_endpoint"] == "http://pc2.example:9224"
    assert status["execution_mode"] == "manual"
    assert status["request_owner"] == "pc2"
    assert status["delegated_to_node_solver"] is True
    assert status["nas_solver_active"] is False
    assert status["node_solver_expected"] is False


def test_force_reset_cannot_clear_a_newer_scoped_challenge(server_runtime, monkeypatch):
    server = server_runtime
    contended = observe_contention(server.RUNTIME, monkeypatch)
    assert server._persist_solver_scope_state("seed", receipt("old")) is None
    clearing, release_reset = threading.Event(), threading.Event()
    writer_started, writer_finished = threading.Event(), threading.Event()
    clear_challenge = server._clear_solver_challenge_state

    def controlled_clear(scope):
        clearing.set()
        assert release_reset.wait(5)
        return clear_challenge(scope)

    def publish_new():
        writer_started.set()
        try:
            return server._persist_solver_scope_state("seed", receipt("new"))
        finally:
            writer_finished.set()

    monkeypatch.setattr(server, "_clear_solver_challenge_state", controlled_clear)
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", dict)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reset = pool.submit(server._force_reset_solver_scope, "seed", "old")
        try:
            assert clearing.wait(5)
            writer = pool.submit(publish_new)
            assert writer_started.wait(5)
            assert contended.wait(5)
            completed_before_reset = writer_finished.is_set()
        finally:
            release_reset.set()
        assert reset.result(timeout=5)["force_reset"] is True
        assert writer.result(timeout=5) is None

    assert server._read_solver_scope_state("seed")["challenge_id"] == "new"
    assert completed_before_reset is False


@pytest.mark.parametrize("reported_id, age", [("stale", 901.0), ("active", 30.0)])
def test_force_reset_rejections_preserve_scoped_receipt(
    server_runtime, reported_id, age
):
    server = server_runtime
    state = {**receipt("active"), "first_seen_epoch": time.time() - age}
    assert server._persist_solver_scope_state("seed", state) is None
    path = server._solver_scope_state_path("seed")
    original = path.read_bytes()

    result = server._force_reset_solver_scope("seed", reported_id)

    assert result["ok"] is False and result["force_reset"] is False
    assert path.read_bytes() == original
    assert server.RUNTIME.control.scope_snapshot("seed")["challenge_id"] == "active"


@pytest.mark.parametrize("entrypoint", ["finalize", "cooldown", "direct"])
def test_auth_finalization_cannot_clear_a_newer_challenge(
    server_runtime, monkeypatch, entrypoint
):
    server = server_runtime
    assert server._persist_solver_scope_state("seed", receipt("old")) is None
    attempted = threading.Event()
    acquired_during_cleanup = []
    writers = []
    clear = server._clear_solver_manual_required_pause_compat
    lock = server.RUNTIME.lock

    def publish_new():
        acquired = lock.acquire(blocking=False)
        acquired_during_cleanup.append(acquired)
        if acquired:
            try:
                return server._persist_solver_scope_state("seed", receipt("new"))
            finally:
                lock.release()
                attempted.set()
        attempted.set()
        return server._persist_solver_scope_state("seed", receipt("new"))

    monkeypatch.setattr(server, "_captcha_solver_runtime_status", dict)
    monkeypatch.setattr(
        server, "_remember_solver_auth_completion", lambda _request: None
    )
    with ThreadPoolExecutor(max_workers=1) as pool:

        def controlled_clear(scope):
            writers.append(pool.submit(publish_new))
            assert attempted.wait(5)
            return clear(scope)

        monkeypatch.setattr(
            server, "_clear_solver_manual_required_pause_compat", controlled_clear
        )
        if entrypoint == "finalize":
            result = server._finalize_auth_completion_after_cookie_snapshot(
                "completion-old",
                expected_challenge_id="old",
                completion_request={"scope": "seed", "target_url": SEED_URL},
            )
        elif entrypoint == "cooldown":
            result = server._collection_observer_resume_after_cooldown_payload(
                {
                    "resume_request_id": "resume-old",
                    "challenge_id": "old",
                    "scope": "seed",
                    "target_url": SEED_URL,
                    "source": "pc2_local_solver",
                }
            )
        else:
            monkeypatch.setattr(
                server, "_solver_target_requires_manual_only", lambda _: False
            )
            monkeypatch.setattr(
                server,
                "_schedule_auth_cookie_snapshot_refresh",
                lambda *_: {"status": "skipped"},
            )
            result = server._collection_observer_auth_complete_payload(
                {
                    "completion_id": "completion-old",
                    "scope": "seed",
                    "source": "operator",
                    "refresh_cookie_snapshot": False,
                }
            )
        assert writers[0].result(timeout=5) is None
    assert result["auth_state_confirmed"] is True
    assert server._read_solver_scope_state("seed")["challenge_id"] == "new"
    assert acquired_during_cleanup == [False]


def test_direct_completion_releases_lock_before_scheduling(server_runtime, monkeypatch):
    server = server_runtime
    assert server._persist_solver_scope_state("seed", receipt("old")) is None
    published = []

    def publish_new():
        with server.RUNTIME.lock:
            assert server._persist_solver_scope_state("seed", receipt("new")) is None
            server.RUNTIME.solver.record_outcome("manual_required", "manual_required")
            return server.RUNTIME.solver.snapshot()

    def schedule(*_args):
        with ThreadPoolExecutor(max_workers=1) as pool:
            published.append(pool.submit(publish_new).result(timeout=5))
        return {"status": "skipped"}

    monkeypatch.setattr(server, "_captcha_solver_runtime_status", dict)
    monkeypatch.setattr(server, "_solver_target_requires_manual_only", lambda _: False)
    monkeypatch.setattr(server, "_remember_solver_auth_completion", lambda _: None)
    monkeypatch.setattr(server, "_schedule_auth_cookie_snapshot_refresh", schedule)
    result = server._collection_observer_auth_complete_payload(
        {
            "completion_id": "completion-old",
            "scope": "seed",
            "source": "operator",
            "refresh_cookie_snapshot": False,
        }
    )
    assert result["auth_state_confirmed"] is True
    assert server._read_solver_scope_state("seed")["challenge_id"] == "new"
    assert server.RUNTIME.solver.snapshot() == published[0]


@pytest.mark.parametrize("scheduler_status", ["pending", "completed"])
def test_async_completion_does_not_overwrite_finalizer_outcome(
    server_runtime, monkeypatch, scheduler_status
):
    server = server_runtime
    assert server._persist_solver_scope_state("seed", receipt("old")) is None
    committed = []
    remembered = []
    finalize = server._finalize_auth_completion_after_cookie_snapshot

    def complete(*args, **kwargs):
        result = finalize(*args, **kwargs)
        assert result["auth_state_confirmed"] is True
        if scheduler_status == "completed":
            assert server._persist_solver_scope_state("seed", receipt("new")) is None
            server.RUNTIME.solver.record_outcome("manual_required", "manual_required")
        committed.append(server.RUNTIME.solver.snapshot())
        return result

    def schedule(_payload, completion_id, **kwargs):
        if scheduler_status == "pending":
            # The worker can finish before the caller consumes its pending response.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(
                    complete,
                    completion_id,
                    expected_challenge_id=kwargs["expected_challenge_id"],
                    completion_request=kwargs["completion_request"],
                ).result(timeout=5)
        return {
            "status": scheduler_status,
            "refreshed": scheduler_status == "completed",
        }

    monkeypatch.setattr(server, "_captcha_solver_runtime_status", dict)
    monkeypatch.setattr(server, "_remember_solver_auth_completion", remembered.append)
    monkeypatch.setattr(server, "_schedule_auth_cookie_snapshot_refresh", schedule)
    monkeypatch.setattr(
        server, "_finalize_auth_completion_after_cookie_snapshot", complete
    )
    server._collection_observer_auth_complete_payload(
        {
            "completion_id": "completion-old",
            "scope": "seed",
            "refresh_cookie_snapshot": True,
        }
    )
    assert server.RUNTIME.solver.snapshot() == committed[0]
    assert len(remembered) == 1
    if scheduler_status == "pending":
        assert server.RUNTIME.control.scope_snapshot("seed")["paused"] is False
    else:
        assert server._read_solver_scope_state("seed")["challenge_id"] == "new"


@pytest.mark.parametrize("publish_challenge", [False, True])
def test_confirmed_completion_replay_preserves_grace_and_outcome(
    server_runtime, monkeypatch, publish_challenge
):
    server = server_runtime
    assert server._remember_auth_completion_confirmation("completed") is None
    server.RUNTIME.recovery.record_auth_completion(123.0, {"target_url": SEED_URL}, 7)
    before = server.RUNTIME.recovery.snapshot()
    outcomes = []

    def snapshot_status():
        if publish_challenge:
            assert server._persist_solver_scope_state("seed", receipt("new")) is None
            server.RUNTIME.solver.record_outcome("manual_required", "manual_required")
        outcomes.append(server.RUNTIME.solver.snapshot())
        return {"status": "completed", "refreshed": True}

    monkeypatch.setattr(server, "_captcha_solver_runtime_status", dict)
    monkeypatch.setattr(server, "_solver_detail_captured_count", lambda: 7)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_runtime_status", snapshot_status)
    result = server._collection_observer_auth_complete_payload(
        {"completion_id": "completed", "scope": "seed", "source": "operator"}
    )
    assert result["idempotent"] is True
    after = server.RUNTIME.recovery.snapshot()
    assert after.completed_at == before.completed_at
    assert after.completed_request == before.completed_request
    assert after.completed_detail_count == before.completed_detail_count
    assert server.RUNTIME.solver.snapshot() == outcomes[0]
    if publish_challenge:
        assert server._read_solver_scope_state("seed")["challenge_id"] == "new"


@pytest.mark.parametrize("source", ["pc2_local_solver", "seed_auth_probe", "operator"])
def test_completion_preparation_cannot_adopt_a_newer_challenge(
    server_runtime, monkeypatch, source
):
    server = server_runtime
    assert server._persist_solver_scope_state("seed", receipt("old")) is None
    attempted = threading.Event()
    writers, published, scheduled_ids = [], [], []
    lock = server.RUNTIME.lock
    payload_flag = server._payload_flag

    def publish_new():
        acquired = lock.acquire(blocking=False)
        if not acquired:
            attempted.set()
            lock.acquire()
        try:
            assert server._persist_solver_scope_state("seed", receipt("new")) is None
            server.RUNTIME.solver.record_outcome("new_challenge", "manual_required")
            published.append(
                (
                    server._solver_scope_state_path("seed").read_bytes(),
                    server.RUNTIME.solver.snapshot(),
                )
            )
        finally:
            lock.release()
            attempted.set()

    def schedule(_payload, _completion_id, **kwargs):
        writers[0].result(timeout=5)
        scheduled_ids.append(kwargs["expected_challenge_id"])
        return {"status": "completed", "refreshed": True}

    monkeypatch.setattr(server, "_captcha_solver_runtime_status", dict)
    monkeypatch.setattr(server, "_remember_solver_auth_completion", lambda _: None)
    monkeypatch.setattr(server, "_schedule_auth_cookie_snapshot_refresh", schedule)
    with ThreadPoolExecutor(max_workers=1) as pool:

        def controlled_flag(payload, key, default):
            if key == "refresh_cookie_snapshot" and not writers:
                writers.append(pool.submit(publish_new))
                assert attempted.wait(5)
            return payload_flag(payload, key, default)

        monkeypatch.setattr(server, "_payload_flag", controlled_flag)
        result = server._collection_observer_auth_complete_payload(
            {
                "completion_id": "completion-old",
                "challenge_id": "old",
                "scope": "seed",
                "target_url": SEED_URL,
                "source": source,
                "refresh_cookie_snapshot": True,
            }
        )
        writers[0].result(timeout=5)

    assert result["auth_state_confirmed"] is False
    assert scheduled_ids in ([], ["old"])
    assert server._solver_scope_state_path("seed").read_bytes() == published[0][0]
    assert server._read_solver_scope_state("seed")["challenge_id"] == "new"
    assert server.RUNTIME.control.scope_snapshot("seed")["paused"] is True
    assert server.RUNTIME.solver.snapshot() == published[0][1]
    assert not server._auth_completion_was_confirmed("completion-old")
