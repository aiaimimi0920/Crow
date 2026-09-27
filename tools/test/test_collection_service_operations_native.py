"""Native factories and seed entrypoints retain live facade dependencies."""

from types import SimpleNamespace

import pytest

from src.collection_service_operations import CollectionServiceOperations
from src.runtime_state import RuntimeState


@pytest.fixture(params=[False, True])
def host(request):
    from src import server, server_collection_operations

    return server if request.param else server_collection_operations


def test_saved_factories_follow_constructor_paths_repository_adapter_and_lock(
    host, monkeypatch
):
    seed, detail = host._seed_collection_service, host._detail_collection_service
    for name in CollectionServiceOperations.__all__:
        assert isinstance(getattr(host, name).__self__, CollectionServiceOperations)
        if host.__name__ == "src.server":
            assert getattr(host._CONTEXT, name) is getattr(host, name)
    defaults = []
    for index in range(2):
        state = RuntimeState()
        repository, adapter = object(), object()
        monkeypatch.setattr(host, "RUNTIME", state)
        monkeypatch.setattr(host, "DB_REPOSITORY", repository)
        monkeypatch.setattr(host, "DATA_DIR", f"data-{index}")
        monkeypatch.setattr(host, "JOBS_DIR", f"jobs-{index}")
        monkeypatch.setattr(host, "SeedCollectionService", lambda **kwargs: kwargs)
        monkeypatch.setattr(host, "DetailCollectionService", lambda **kwargs: kwargs)
        monkeypatch.setattr(
            host,
            "collection_adapter_from_env",
            lambda *, default, adapter=adapter: defaults.append(default) or adapter,
        )
        assert seed() == {
            "repository": repository,
            "adapter": adapter,
            "data_root": f"data-{index}",
            "jobs_dir": f"jobs-{index}",
        }
        assert detail() == {
            "repository": repository,
            "adapter": adapter,
            "data_root": f"data-{index}",
            "dispatch_lock": state.collection.lock,
        }
        assert detail("override")["data_root"] == "override"
    assert defaults == ["taobao_judicial"] * 6


def test_saved_seed_entrypoints_use_current_service_and_database_callback(
    host, monkeypatch
):
    build, submit = host.build_sniff_stub, host.handle_seed_batch_submission
    state = RuntimeState()
    monkeypatch.setattr(host, "RUNTIME", state)
    for name in (
        "get_data_path",
        "update_file_global",
        "persist_item_to_db",
        "archive_list_payload",
    ):
        monkeypatch.setattr(host, name, lambda *args: None, raising=False)
    calls = []

    def capture(payload, **callbacks):
        calls.append((payload, callbacks))
        return payload

    for _ in range(2):
        service = SimpleNamespace(build_seed_stub=capture, submit_batch=capture)
        monkeypatch.setattr(
            host, "_seed_collection_service", lambda service=service: service
        )
        payload = {"items": []}
        assert build(payload) is payload
        assert calls[-1][1] == {
            "parse_price": host.parse_price,
            "safe_int": host._safe_int,
        }
        assert submit(payload) is payload
        callbacks = calls[-1][1]
        monkeypatch.setattr(host, "DB_REPOSITORY", SimpleNamespace(enabled=False))
        assert callbacks["get_flat_item"]("item") is None
        monkeypatch.setattr(
            host,
            "DB_REPOSITORY",
            SimpleNamespace(
                enabled=True, get_flat_item=lambda item_id: {"id": item_id}
            ),
        )
        assert callbacks["get_flat_item"]("item") == {"id": "item"}
        assert callbacks["set_seen"].__self__ is state.collection
        assert callbacks["queue_pending"].__self__ is state.collection
