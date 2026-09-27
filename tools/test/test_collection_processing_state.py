"""The collection processing registry prevents duplicate work atomically."""

from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from src.collection_processing_state import CollectionProcessingState


def test_claim_is_atomic_under_concurrent_workers():
    state = CollectionProcessingState()
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: state.claim("item.html"), range(8)))

    assert claims.count(True) == 1
    assert state.snapshot() == frozenset({"item.html"})


def test_release_and_set_compatibility_are_idempotent():
    state = CollectionProcessingState()
    state.add("one")
    state.add("one")
    assert "one" in state
    state.release("one")
    state.release("one")
    assert len(state) == 0


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled", "rejected"])
def test_submission_releases_original_runtime_only(monkeypatch, outcome):
    from src import server
    from src.runtime_state import RuntimeState

    original, replacement = RuntimeState(), RuntimeState()
    path = "synthetic-item.html"
    replacement.processing.claim(path)
    future = Future()

    def submit(*_args):
        monkeypatch.setattr(server, "RUNTIME", replacement)
        if outcome == "rejected":
            raise RuntimeError("synthetic executor rejection")
        return future

    monkeypatch.setattr(server, "RUNTIME", original)
    monkeypatch.setattr(server, "executor", SimpleNamespace(submit=submit))
    server.submit_task(path)
    if outcome == "completed":
        future.set_result(None)
    elif outcome == "failed":
        future.set_exception(RuntimeError("synthetic worker failure"))
    elif outcome == "cancelled":
        future.cancel()

    assert original.processing.snapshot() == frozenset()
    assert replacement.processing.snapshot() == frozenset({path})


def test_worker_cannot_release_claim_before_future_completion(monkeypatch, tmp_path):
    from src import server
    from src.collection.detail_service import DetailCollectionService
    from src.runtime_state import RuntimeState

    state = RuntimeState()
    path = str(tmp_path / "item-missing.html")
    future = Future()
    submissions = []

    def submit(worker, file_path):
        submissions.append(file_path)
        worker(file_path)
        return future

    monkeypatch.setattr(server, "RUNTIME", state)
    monkeypatch.setattr(server, "executor", SimpleNamespace(submit=submit))
    monkeypatch.setattr(
        server, "_detail_collection_service", lambda: DetailCollectionService(tmp_path)
    )
    server.submit_task(path)
    assert path in state.processing
    server.submit_task(path)
    assert submissions == [path]
    future.set_result(None)
    assert path not in state.processing


@pytest.mark.parametrize("facade", [False, True])
def test_saved_native_submission_uses_current_executor_and_worker(monkeypatch, facade):
    from src import server, server_collection_operations
    from src.collection_file_runtime import CollectionFileRuntime
    from src.runtime_state import RuntimeState

    host = server if facade else server_collection_operations
    submit_task = host.submit_task
    assert isinstance(submit_task.__self__, CollectionFileRuntime)
    if facade:
        assert server._CONTEXT.submit_task is submit_task
    for _ in range(2):
        state = RuntimeState()
        future = Future()
        calls = []
        worker = lambda _path: None

        def submit(fn, path, calls=calls, future=future):
            calls.append((fn, path))
            return future

        monkeypatch.setattr(host, "RUNTIME", state)
        monkeypatch.setattr(host, "executor", SimpleNamespace(submit=submit))
        monkeypatch.setattr(host, "process_single_file", worker, raising=False)
        submit_task("item.html")
        submit_task("item.html")
        assert calls == [(worker, "item.html")]
        assert "item.html" in state.processing
        future.set_result(None)
        assert "item.html" not in state.processing
