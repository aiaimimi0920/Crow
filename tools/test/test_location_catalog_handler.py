"""Location catalog merge preserves names, legacy IDs, and current runtime lock."""

from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "RUNTIME", SimpleNamespace(file_lock=RLock()))
    monkeypatch.setattr(server, "_require_control_plane", Mock(return_value=True))
    monkeypatch.setattr(server, "_read_json_body", Mock(return_value=(True, {})))
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    return server, handler, tmp_path


def test_merge_keeps_existing_names_and_missing_code_conversion(catalog):
    from src.archive_json_io import read_records, write_records

    host, handler, root = catalog
    path = root / "collected_locations.json"
    write_records(path, [{"code": "1", "name": "original"}])
    host._read_json_body.return_value = (
        True,
        {
            "locations": [
                {"code": 1, "name": "replacement"},
                {"code": 2, "name": "new"},
                {"name": "missing"},
            ]
        },
    )
    host._post_save_locations(handler)
    assert read_records(path) == [
        {"code": "1", "name": "original"},
        {"code": "2", "name": "new"},
        {"code": "None", "name": "missing"},
    ]
    handler.send_json.assert_called_once_with({"status": "ok", "count": 3})


def test_unchanged_catalog_is_not_rewritten(catalog, monkeypatch):
    from src import archive_json_io

    host, handler, root = catalog
    path = root / "collected_locations.json"
    archive_json_io.write_records(path, [{"code": "1", "name": "original"}])
    before = path.read_bytes()
    write = Mock(side_effect=AssertionError("unnecessary rewrite"))
    monkeypatch.setattr(archive_json_io, "write_records", write)
    host._read_json_body.return_value = (
        True,
        {"locations": [{"code": "1", "name": "new"}]},
    )
    host._post_save_locations(handler)
    write.assert_not_called()
    assert path.read_bytes() == before
    handler.send_json.assert_called_once_with({"status": "ok", "count": 1})


def test_guard_and_body_rejection_do_not_touch_catalog(catalog):
    host, handler, root = catalog
    host._require_control_plane.return_value = False
    host._post_save_locations(handler)
    host._read_json_body.assert_not_called()
    host._require_control_plane.return_value = True
    host._read_json_body.return_value = False, {}
    host._post_save_locations(handler)
    assert not (root / "collected_locations.json").exists()
    handler.send_json.assert_not_called()


def test_catalog_native_descriptor():
    from src import location_catalog_handler, server

    handler = object.__new__(server.DataHandler)
    assert handler._post_save_locations.__self__ is handler
    assert handler._post_save_locations.__func__ is server._post_save_locations
    assert server._post_save_locations.__module__ == location_catalog_handler.__name__
    assert server._CONTEXT._post_save_locations is server._post_save_locations
