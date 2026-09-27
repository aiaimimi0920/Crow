"""Working-item cache identity, database fallback and live native dependencies."""

from types import SimpleNamespace

import pytest

from src.runtime_state import RuntimeState


@pytest.fixture(params=[False, True])
def host(request):
    from src import server, server_collection_operations

    return server if request.param else server_collection_operations


def test_database_item_without_date_gets_local_archive_path(host, monkeypatch):
    state = RuntimeState()
    item = {"id": "item"}
    dates = []
    monkeypatch.setattr(host, "RUNTIME", state)
    monkeypatch.setattr(
        host,
        "DB_REPOSITORY",
        SimpleNamespace(enabled=True, get_flat_item=lambda _id: item),
    )
    monkeypatch.setattr(host, "sync_collection_record", lambda _item: None)
    monkeypatch.setattr(
        host,
        "get_data_path",
        lambda date: dates.append(date) or "archive.json",
        raising=False,
    )
    entry = host._get_working_item("item")
    assert entry == {"data": item, "file_path": "archive.json", "cached": False}
    assert dates[0].year > 2020
    assert state.collection.get_seen("item") is None


def test_saved_native_cache_access_and_eviction_follow_runtime(host, monkeypatch):
    from src.collection_working_items import CollectionWorkingItems

    get = host._get_working_item
    evict = host._evict_runtime_item
    for name in CollectionWorkingItems.__all__:
        assert isinstance(getattr(host, name).__self__, CollectionWorkingItems)
        if host.__name__ == "src.server":
            assert getattr(host._CONTEXT, name) is getattr(host, name)
    for _ in range(2):
        state = RuntimeState()
        data = {"is_processed": True}
        state.collection.set_seen("12", {"data": data, "file_path": "cached.json"})
        state.collection.queue_pending("12")
        state.collection.mark_dispatched("12", "retained")
        monkeypatch.setattr(host, "RUNTIME", state)
        monkeypatch.setattr(host, "DB_REPOSITORY", SimpleNamespace(enabled=True))
        entry = get(12)
        assert entry == {"data": data, "file_path": "cached.json", "cached": True}
        assert entry["data"] is data
        evict(12)
        assert state.collection.get_seen("12") is None
        assert state.collection.pending_tasks == []
        assert state.collection.get_dispatched("12") == "retained"


def test_database_processed_filter_runs_after_sync(host, monkeypatch):
    item = {"id": "db", "auction_date": "2026-09-25", "is_processed": True}
    calls = []
    monkeypatch.setattr(host, "RUNTIME", RuntimeState())
    monkeypatch.setattr(
        host,
        "DB_REPOSITORY",
        SimpleNamespace(enabled=True, get_flat_item=lambda _id: item),
    )
    monkeypatch.setattr(host, "sync_collection_record", calls.append)
    monkeypatch.setattr(host, "get_data_path", lambda date: date, raising=False)
    assert host._get_working_item("db") is None
    assert calls == [item]
    entry = host._get_working_item("db", include_processed=True)
    assert entry == {"data": item, "file_path": "2026-09-25", "cached": False}
    assert calls == [item, item]


def test_repository_errors_return_none_but_sync_errors_propagate(
    host, monkeypatch, caplog
):
    monkeypatch.setattr(host, "RUNTIME", RuntimeState())

    def fail(_item):
        raise OSError("isolated working-item failure")

    repository = SimpleNamespace(enabled=True, get_flat_item=fail)
    monkeypatch.setattr(host, "DB_REPOSITORY", repository)
    assert host._get_working_item("db") is None
    assert "Working item fetch failed item=db" in caplog.text
    repository.get_flat_item = lambda _id: {"id": "db"}
    monkeypatch.setattr(host, "sync_collection_record", fail)
    with pytest.raises(OSError, match="isolated working-item failure"):
        host._get_working_item("db")


def test_db_preference_short_circuits_disabled_repository(host, monkeypatch):
    calls = []
    prefer = host._prefer_db_task_reads
    monkeypatch.setattr(
        host, "_runtime_env_flag", lambda *args: calls.append(args) or False
    )
    monkeypatch.setattr(host, "DB_REPOSITORY", SimpleNamespace(enabled=False))
    assert prefer() is False
    assert calls == []
    monkeypatch.setattr(host, "DB_REPOSITORY", SimpleNamespace(enabled=True))
    assert prefer() is False
    assert calls == [("FAPAI_DB_PREFER_RUNTIME_INDEX", True)]
