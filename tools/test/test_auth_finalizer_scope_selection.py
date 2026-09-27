"""Finalizer scope fallback and scoped receipt publication share one transaction."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.runtime_state import RuntimeState


@pytest.fixture
def server_runtime(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    return server


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("explicit_scope", [False, True])
@pytest.mark.parametrize("publication", ["before_selection", "during_selection"])
def test_scope_publication_cannot_be_erased_by_legacy_fallback(
    server_runtime, monkeypatch, scope, explicit_scope, publication
):
    server = server_runtime
    request = {
        "target_url": "https://sf.taobao.com/list/1.htm"
        if scope == "seed"
        else "https://sf-item.taobao.com/sf_item/3001.htm",
    }
    if explicit_scope:
        request["scope"] = scope
    # A legacy receipt may exist without a scoped counterpart after migration.
    assert server._persist_solver_challenge_state("legacy", request) is None
    server.RUNTIME.recovery.set_challenge("legacy", request)
    assert server._mark_solver_manual_required(manual_only=True) is None
    state = server._new_solver_scope_state()
    state.update(
        challenge_id="new-scoped",
        paused=True,
        pause_reason="manual_required",
        manual_required=True,
        manual_only=True,
        last_request={**request, "scope": scope, "node_id": "new-owner"},
    )
    path = server._solver_scope_state_path(scope)
    attempted = threading.Event()
    lock = server.RUNTIME.lock

    def publish():
        acquired = lock.acquire(blocking=False)
        if not acquired:
            attempted.set()
            lock.acquire()
        try:
            # Use the actual independently callable scoped publication boundary.
            assert server._persist_solver_scope_state(scope, state) is None
            return path.read_bytes()
        finally:
            lock.release()
            attempted.set()

    status = server._solver_scope_runtime_status
    writers = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        if publication == "before_selection":
            writers.append(pool.submit(publish))
            writers[0].result(timeout=5)
        else:

            def observed_status(candidate, now=None):
                snapshot = status(candidate, now=now)
                if candidate == scope and not writers:
                    writers.append(pool.submit(publish))
                    assert attempted.wait(5)
                return snapshot

            monkeypatch.setattr(server, "_solver_scope_runtime_status", observed_status)
        result = server._finalize_auth_completion_after_cookie_snapshot(
            "legacy-completion",
            expected_challenge_id="legacy",
            completion_request=request,
        )
        published_bytes = writers[0].result(timeout=5)

    if publication == "before_selection":
        assert result["auth_state_confirmed"] is False
        assert result["stale_challenge"] is True
        assert not server._auth_completion_was_confirmed("legacy-completion")
    else:
        assert result["auth_state_confirmed"] is True
    assert path.exists(), "legacy completion erased the newer scoped receipt"
    assert path.read_bytes() == published_bytes
    current = status(scope)
    assert current["challenge_id"] == "new-scoped"
    assert current["paused"] is True
    assert current["manual_required"] is True
    assert current["manual_only"] is True
    assert current["last_request"] == state["last_request"]
