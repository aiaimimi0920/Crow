"""Area write compatibility keeps processing flags and HTTP error boundaries."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("name", ["_post_area_result", "_post_approve_area"])
def test_native_area_write_descriptor(name):
    from src import detail_ingest_handlers, server

    handler = object.__new__(server.DataHandler)
    method = getattr(handler, name)
    assert method.__self__ is handler
    assert method.__func__ is getattr(server, name)
    assert method.__module__ == detail_ingest_handlers.__name__
    assert getattr(server._CONTEXT, name) is method.__func__


@pytest.fixture(params=["_post_area_result", "_post_approve_area"])
def area(request, monkeypatch):
    from src import server

    index = SimpleNamespace(remove_pending=Mock())
    action = Mock(return_value={"status": "ok", "extra": "kept"})
    reader = Mock(return_value=(True, {"id": " item "}))
    monkeypatch.setattr(server, "_collection_runtime_index", Mock(return_value=index))
    monkeypatch.setattr(server, "_read_json_body", reader)
    monkeypatch.setattr(
        server,
        "_detail_collection_service",
        lambda: SimpleNamespace(apply_working_item_patch=action),
    )
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    return server, request.param, handler, index, action


@pytest.mark.parametrize("item_id", [None, "", " item "])
def test_area_write_preserves_id_conversion_and_processed_flags(area, item_id):
    host, name, handler, index, action = area
    payload = {"id": item_id}
    host._read_json_body.return_value = True, payload
    getattr(host, name)(handler)
    args = action.call_args.kwargs
    assert args["item_id"] == str(item_id)
    assert args["patch_data"] is payload
    assert args["mark_processed"] is True
    assert args["remove_pending"] is index.remove_pending
    assert args["event_type"] == (
        "area_result" if name == "_post_area_result" else "manual_approve_area"
    )
    if name == "_post_approve_area":
        assert args["force_status"] == "done"
    else:
        assert "force_status" not in args
    handler.send_json.assert_called_once_with({"status": "ok", "extra": "kept"})


def test_rejected_area_body_never_acquires_index(area):
    host, name, handler, _, action = area
    host._read_json_body.return_value = False, {}
    getattr(host, name)(handler)
    host._collection_runtime_index.assert_not_called()
    action.assert_not_called()
    handler.send_json.assert_not_called()


def test_area_index_failure_maps_to_route_error(area):
    host, name, handler, _, action = area
    host._collection_runtime_index.side_effect = RuntimeError("index unavailable")
    getattr(host, name)(handler)
    error = handler.send_error_json.call_args.kwargs
    assert error["status"] == 500
    assert error["code"] == (
        "AVM_DETAIL_AREA_RESULT_FAILED"
        if name == "_post_area_result"
        else "AVM_DETAIL_APPROVE_AREA_FAILED"
    )
    assert error["details"] == {"error": "index unavailable"}
    action.assert_not_called()


def test_area_non_ok_result_keeps_not_found_response(area):
    host, name, handler, _, action = area
    action.return_value = {"status": "unexpected"}
    getattr(host, name)(handler)
    assert handler.send_error_json.call_args.kwargs["status"] == 404
    assert (
        handler.send_error_json.call_args.kwargs["code"] == "AVM_DETAIL_ITEM_NOT_FOUND"
    )
