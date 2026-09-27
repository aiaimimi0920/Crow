"""Collection console HTTP reads preserve wire bytes and detail query semantics."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_native_read_descriptors():
    from src import collection_read_handlers, server

    handler = object.__new__(server.DataHandler)
    for name in collection_read_handlers.CollectionReadHandlers.__all__:
        method = getattr(handler, name)
        assert method.__self__ is handler
        assert method.__func__ is getattr(server, name)
        assert method.__module__ == collection_read_handlers.__name__
        assert getattr(server._CONTEXT, name) is method.__func__


@pytest.mark.parametrize("asset", [False, True])
def test_console_preserves_response_bytes_and_headers(monkeypatch, asset):
    from src import server

    handler = SimpleNamespace(
        send_response=Mock(), send_header=Mock(), end_headers=Mock(), wfile=BytesIO()
    )
    body = b"\x00\xffasset" if asset else "<p>中文</p>".encode()
    content_type = "application/octet-stream" if asset else "text/html; charset=utf-8"
    saved = server._get_collection_asset if asset else server._get_collection_index
    if asset:
        callback = Mock(return_value=(body, content_type))
        monkeypatch.setattr(server, "_collection_observer_static_asset", callback)
    else:
        callback = Mock(return_value=body.decode())
        monkeypatch.setattr(server, "_collection_observer_page_html", callback)
    saved(handler, None, "/collection/assets/file", {})
    callback.assert_called_once_with(*(["/collection/assets/file"] if asset else []))
    handler.send_response.assert_called_once_with(200)
    assert handler.send_header.call_args_list == [
        (("Content-Type", content_type),),
        (("Content-Length", str(len(body))),),
    ]
    handler.end_headers.assert_called_once_with()
    assert handler.wfile.getvalue() == body


def test_encoded_detail_path_overrides_query_without_mutation(monkeypatch):
    from src import server

    query = {"item_id": ["ignored"], "other": ["retained"]}
    payload = {"found": True}
    callback = Mock(return_value=payload)
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    saved = server._get_collection_item
    monkeypatch.setattr(
        server,
        "DB_REPOSITORY",
        SimpleNamespace(enabled=True, collection_observer_item_detail=Mock()),
    )
    monkeypatch.setattr(server, "_collection_observer_item_payload", callback)
    saved(handler, None, "/api/collection/items/a%2Fb", query)
    callback.assert_called_once_with({"item_id": ["a/b"], "other": ["retained"]})
    assert query["item_id"] == ["ignored"]
    handler.send_json.assert_called_once_with(payload)


@pytest.mark.parametrize("suffix", ["overview", "items", "regions"])
def test_saved_read_uses_current_payload_callback(monkeypatch, suffix):
    from src import server

    query = {"region": ["x"]}
    saved = getattr(server, "_get_collection_" + suffix)
    callback = Mock(return_value={"ok": True})
    monkeypatch.setattr(server, "_collection_observer_" + suffix + "_payload", callback)
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    saved(handler, None, "unused", query)
    callback.assert_called_once_with(*([] if suffix == "overview" else [query]))
    handler.send_json.assert_called_once_with({"ok": True})
