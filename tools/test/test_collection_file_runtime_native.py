"""Native file runtime publication, live detail callbacks and scanner behavior."""

from types import SimpleNamespace

import pytest

from src.collection_file_runtime import CollectionFileRuntime
from src.runtime_state import RuntimeState


class EndScan(BaseException):
    """End the infinite worker without exercising its exception retry path."""


@pytest.fixture(params=[False, True])
def host(request):
    from src import server, server_data_runtime

    return server if request.param else server_data_runtime


def test_data_runtime_has_left_cloning_without_losing_public_exports():
    from src import runtime_json, server, server_data_runtime

    assert not hasattr(server, "_IMPLEMENTATION_MODULES")
    assert server.load_json_file is runtime_json.load_json_file
    for name in server_data_runtime.__all__:
        assert callable(getattr(server, name))
        assert getattr(server._CONTEXT, name) is getattr(server, name)
    for name in ("process_single_file", "background_file_processor"):
        assert isinstance(getattr(server, name).__self__, CollectionFileRuntime)
        assert isinstance(
            getattr(server_data_runtime, name).__self__, CollectionFileRuntime
        )


def test_saved_processing_method_uses_replaced_service_and_callbacks(host, monkeypatch):
    process = host.process_single_file
    for _ in range(2):
        collection = RuntimeState().collection
        calls = []
        monkeypatch.setattr(
            host,
            "_collection_runtime_index",
            lambda collection=collection: collection,
            raising=False,
        )
        service = SimpleNamespace(
            process_html_file=lambda *args, calls=calls, **kwargs: calls.append(
                (args, kwargs)
            )
        )
        monkeypatch.setattr(
            host,
            "_detail_collection_service",
            lambda service=service: service,
            raising=False,
        )
        names = {
            "get_working_item": "_get_working_item",
            "get_data_path": "get_data_path",
            "update_item_in_json": "update_item_in_json",
            "remove_item_from_json": "remove_item_from_json",
            "persist_item_to_db": "persist_item_to_db",
            "mark_item_deleted_in_db": "mark_item_deleted_in_db",
            "evict_runtime_item": "_evict_runtime_item",
            "prefer_db_task_reads": "_prefer_db_task_reads",
            "sync_avm_risk_aliases": "sync_avm_risk_aliases",
        }
        expected = {key: (lambda: None) for key in names}
        for key, name in names.items():
            monkeypatch.setattr(host, name, expected[key], raising=False)
        model = SimpleNamespace(
            extract_auction_data=lambda: None,
            extract_avm_risk_features=lambda: None,
            log_prediction_event=lambda: None,
        )
        monkeypatch.setattr(host, "llm_helper", model)
        process("evidence.html")
        args, callbacks = calls[0]
        assert args == ("evidence.html",)
        assert all(callbacks[key] is callback for key, callback in expected.items())
        assert callbacks["extract_auction_data"] is model.extract_auction_data
        assert callbacks["extract_avm_risk_features"] is model.extract_avm_risk_features
        assert callbacks["log_prediction_event"] is model.log_prediction_event
        for key in ("queue_pending", "set_seen", "remove_pending"):
            assert callbacks[key].__self__ is collection


@pytest.mark.parametrize("mode", ["files", "empty", "failure"])
def test_scanner_order_processing_skip_and_backoff(host, tmp_path, monkeypatch, mode):
    scanner = host.background_file_processor
    runtime = RuntimeState()
    submitted = []
    delays = []
    monkeypatch.setattr(host, "RUNTIME", runtime)
    monkeypatch.setattr(host, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(host, "submit_task", submitted.append, raising=False)

    def sleep(seconds):
        delays.append(seconds)
        raise EndScan

    monkeypatch.setattr(host, "time", SimpleNamespace(sleep=sleep))
    expected = []
    if mode == "files":
        (tmp_path / "html").mkdir()
        paths = [
            tmp_path / "item-a.txt",
            tmp_path / "html/item-b.html",
            tmp_path / "item-c.html",
        ]
        for path in paths:
            path.write_text("evidence", encoding="utf-8")
        blocked = tmp_path / "item-busy.txt"
        blocked.write_text("busy", encoding="utf-8")
        runtime.processing.add(str(blocked))
        expected = [str(path) for path in paths]
    elif mode == "failure":

        def fail(_pattern):
            raise OSError("isolated scan failure")

        monkeypatch.setattr(host, "glob", SimpleNamespace(glob=fail))
    with pytest.raises(EndScan):
        scanner()
    assert submitted == expected
    assert delays == [5 if mode == "failure" else 1]
