"""Collection DB callbacks preserve native identity and late repository replacement."""

from types import SimpleNamespace

import pytest

from src.collection_database_writes import CollectionDatabaseWrites


@pytest.mark.parametrize("facade", [False, True])
def test_saved_write_callbacks_follow_repository_and_preserve_payload(
    monkeypatch, facade
):
    from src import server, server_data_runtime

    host = server if facade else server_data_runtime
    upsert = host.persist_item_to_db
    delete = host.mark_item_deleted_in_db
    assert isinstance(upsert.__self__, CollectionDatabaseWrites)
    assert delete.__self__ is upsert.__self__
    if facade:
        assert server._CONTEXT.persist_item_to_db is upsert
        assert server._CONTEXT.mark_item_deleted_in_db is delete
    item = {"id": "item", "source": {"item_id": "source"}}
    payload = {"evidence": ["archive"]}
    for _ in range(2):
        calls = []
        repository = SimpleNamespace(
            upsert_flat_item=lambda *args, calls=calls, **kwargs: calls.append(
                (args, kwargs)
            ),
            mark_deleted=lambda *args, calls=calls, **kwargs: calls.append(
                (args, kwargs)
            ),
        )
        monkeypatch.setattr(host, "DB_REPOSITORY", repository)
        assert upsert(item, "detail", payload) is None
        assert delete(123, "rejected", payload) is None
        assert calls == [
            ((item,), {"event_type": "detail", "event_payload": payload}),
            (("123",), {"reason": "rejected", "event_payload": payload}),
        ]
        assert calls[0][0][0] is item
        assert all(kwargs["event_payload"] is payload for _, kwargs in calls)


@pytest.mark.parametrize("facade", [False, True])
@pytest.mark.parametrize("operation", ["upsert", "delete"])
def test_write_failure_propagates_original_exception(
    monkeypatch, caplog, facade, operation
):
    from src import server, server_data_runtime

    host = server if facade else server_data_runtime
    failure = OSError("storage unavailable")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(
        host, "DB_REPOSITORY", SimpleNamespace(upsert_flat_item=fail, mark_deleted=fail)
    )
    with pytest.raises(OSError) as caught:
        if operation == "upsert":
            host.persist_item_to_db({"source": {"item_id": "source-only"}}, "detail")
        else:
            host.mark_item_deleted_in_db("source-only", "rejected")
    assert caught.value is failure
    assert "source-only" in caplog.text
