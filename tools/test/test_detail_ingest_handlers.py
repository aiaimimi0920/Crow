"""Detail HTTP writes retain current dependencies and admission boundaries."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

CASES = [
    ("_post_detail_update_item", "apply_working_item_patch"),
    ("_post_detail_html", "submit_html"),
]
CALLBACKS = {
    "get_working_item": "_get_working_item",
    "apply_flat_override_patch": "_apply_flat_override_patch",
    "reset_structured_sections_for_resync": "_reset_structured_sections_for_resync",
    "update_file_global": "update_file_global",
    "persist_item_to_db": "persist_item_to_db",
    "evict_runtime_item": "_evict_runtime_item",
    "prefer_db_task_reads": "_prefer_db_task_reads",
}


@pytest.mark.parametrize("name", [case[0] for case in CASES])
def test_native_detail_ingest_descriptors(name):
    from src import detail_ingest_handlers, server

    handler = object.__new__(server.DataHandler)
    method = getattr(handler, name)
    assert method.__self__ is handler
    assert method.__func__ is getattr(server, name)
    assert method.__module__ == detail_ingest_handlers.__name__
    assert getattr(server._CONTEXT, name) is method.__func__


@pytest.fixture(params=CASES)
def ingest(request, monkeypatch):
    from src import server

    name, operation = request.param
    data = {"id": " item ", "html": "<p>evidence</p>", "status": "failed_timeout"}
    index = SimpleNamespace(remove_pending=Mock())
    action = Mock(return_value={"status": "ok", "extra": "kept"})
    service = SimpleNamespace(**{operation: action})
    monkeypatch.setattr(server, "_collection_runtime_index", Mock(return_value=index))
    monkeypatch.setattr(server, "_read_json_body", Mock(return_value=(True, data)))
    monkeypatch.setattr(
        server, "_detail_collection_service", Mock(return_value=service)
    )
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    return server, name, handler, data, index, action


def test_detail_write_uses_current_dependencies(ingest, monkeypatch):
    host, name, handler, data, index, action = ingest
    saved = getattr(host, name)
    for attribute in (*CALLBACKS.values(), "submit_task"):
        monkeypatch.setattr(host, attribute, Mock())
    saved(handler)
    args = action.call_args.kwargs
    assert args["item_id"] == "item"
    for argument, attribute in CALLBACKS.items():
        assert args[argument] is getattr(host, attribute)
    assert args["remove_pending"] is index.remove_pending
    if name == "_post_detail_update_item":
        host._read_json_body.assert_called_once_with(handler)
        assert args["patch_data"] is data
        assert args["event_type"] == "update_item"
        assert args["force_status"] == "failed_timeout"
        handler.send_json.assert_called_once_with({"status": "updated"})
    else:
        host._read_json_body.assert_called_once_with(
            handler, max_bytes=host.REQUEST_BODY_HTML_MAX_BYTES
        )
        assert args["submit_task"] is host.submit_task
        assert args["html_content"] == data["html"]
        assert args["status"] == data["status"]
        handler.send_json.assert_called_once_with({"status": "ok", "extra": "kept"})


def test_detail_write_body_rejection_never_resolves_service(ingest):
    host, name, handler, _, _, action = ingest
    host._read_json_body.return_value = False, {}
    getattr(host, name)(handler)
    host._collection_runtime_index.assert_called_once_with()
    host._detail_collection_service.assert_not_called()
    action.assert_not_called()
    handler.send_json.assert_not_called()


def test_detail_index_failure_stays_outside_http_error_boundary(ingest):
    host, name, handler, _, _, _ = ingest
    host._collection_runtime_index.side_effect = RuntimeError("index unavailable")
    with pytest.raises(RuntimeError, match="index unavailable"):
        getattr(host, name)(handler)
    host._read_json_body.assert_not_called()
    handler.send_error_json.assert_not_called()


def test_detail_service_failure_keeps_route_error_code(ingest):
    host, name, handler, _, _, action = ingest
    action.side_effect = OSError("publication failed")
    getattr(host, name)(handler)
    error = handler.send_error_json.call_args.kwargs
    assert error["status"] == 500
    assert error["code"] == (
        "AVM_DETAIL_UPDATE_ITEM_FAILED"
        if name == "_post_detail_update_item"
        else "AVM_DETAIL_ANALYZE_HTML_FAILED"
    )
    assert error["details"] == {"error": "publication failed"}
    handler.send_json.assert_not_called()
