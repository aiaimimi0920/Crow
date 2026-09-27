"""Upload framing is bounded and rejected bodies cannot alter saved evidence."""

import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_native_upload_binding_and_descriptor():
    from src import server, upload_handler

    handler = object.__new__(server.DataHandler)
    assert handler._post_upload.__self__ is handler
    assert handler._post_upload.__func__ is server._post_upload
    assert server._post_upload.__module__ == upload_handler.__name__
    assert server._resolve_upload_target.__module__ == upload_handler.__name__
    assert server._CONTEXT._post_upload is server._post_upload
    assert server._CONTEXT._resolve_upload_target is server._resolve_upload_target


@pytest.fixture
def upload(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "UPLOAD_MAX_BYTES", 8)
    handler = SimpleNamespace(
        path="/api/upload?id=record&name=detail.html",
        headers={"Content-Length": "8"},
        rfile=Mock(wraps=io.BytesIO(b"evidence")),
        close_connection=False,
        send_json=Mock(),
        send_error_json=Mock(),
    )
    return server, handler, tmp_path


@pytest.mark.parametrize(
    "headers, expected",
    [
        ({}, 400),
        ({"Content-Length": "bad"}, 400),
        ({"Content-Length": "0"}, 400),
        ({"Content-Length": "-2"}, 400),
        ({"Content-Length": "8", "Transfer-Encoding": "chunked"}, 400),
        ({"Content-Length": "9"}, 413),
    ],
)
def test_invalid_framing_closes_without_reading_or_writing(upload, headers, expected):
    host, handler, root = upload
    handler.headers = headers
    host._post_upload(handler)
    assert handler.send_error_json.call_args.kwargs["status"] == expected
    assert handler.close_connection is True
    handler.rfile.read.assert_not_called()
    handler.send_json.assert_not_called()
    assert not (root / "downloads").exists()


def test_truncated_body_never_creates_target(upload):
    host, handler, root = upload
    handler.rfile = Mock(wraps=io.BytesIO(b"short"))
    host._post_upload(handler)
    handler.rfile.read.assert_called_once_with(8)
    assert handler.send_error_json.call_args.kwargs["message"] == "Incomplete upload"
    assert handler.close_connection is True
    assert not (root / "downloads").exists()


def test_invalid_target_drains_bounded_body(upload):
    host, handler, root = upload
    handler.path = "/api/upload?id=record&name=..%2Fescape"
    host._post_upload(handler)
    handler.rfile.read.assert_called_once_with(8)
    assert (
        handler.send_error_json.call_args.kwargs["code"] == "AVM_INVALID_UPLOAD_REQUEST"
    )
    assert handler.close_connection is False
    assert not (root / "downloads").exists()


def test_exact_limit_upload_and_existing_archive_preservation(upload):
    host, handler, root = upload
    host._post_upload(handler)
    target = root / "downloads" / "record" / "detail.html"
    assert target.read_bytes() == b"evidence"
    handler.send_json.assert_called_once_with({"status": "saved"})
    handler.rfile = io.BytesIO(b"replaced")
    host._post_upload(handler)
    assert handler.send_error_json.call_args.kwargs["status"] == 409
    assert target.read_bytes() == b"evidence"


def test_saved_upload_resolves_current_host_target(upload, monkeypatch):
    host, handler, root = upload
    saved = host._post_upload
    resolver = Mock(return_value=None)
    monkeypatch.setattr(host, "_resolve_upload_target", resolver)
    saved(handler)
    resolver.assert_called_once_with("record", "detail.html")
    assert not (root / "downloads").exists()


def test_saved_resolver_uses_new_root(upload, monkeypatch):
    host, _, root = upload
    saved = host._resolve_upload_target
    monkeypatch.setattr(host, "DATA_DIR", root / "new")
    directory, target = saved("record", " file.bin ")
    assert target == str((root / "new" / "downloads" / "record" / "file.bin").resolve())
    assert directory == str((root / "new" / "downloads" / "record").resolve())
