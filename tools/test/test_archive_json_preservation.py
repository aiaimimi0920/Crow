"""Unreadable archive data must never become an empty successful write."""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src import archive_json_io, server_handler_analysis
from src.collection_archive_records import CollectionArchiveRecords
from src.runtime_json import load_json_file
from src.runtime_state import RuntimeState


@pytest.fixture
def native_archive():
    runtime = RuntimeState()
    return CollectionArchiveRecords(
        runtime=lambda: runtime, exists=os.path.exists, load=load_json_file
    )


@pytest.mark.parametrize("operation", ["update_file_global", "remove_item_from_json"])
@pytest.mark.parametrize("failure", ["fsync", "replace"])
def test_legacy_archive_publish_failure_keeps_confirmed_bytes(
    tmp_path, monkeypatch, caplog, operation, failure, native_archive
):
    archive = tmp_path / "archive.json"
    raw = b'[{"id":"target"},{"id":"keep","evidence":"confirmed"}]'
    archive.write_bytes(raw)

    def fail(*_args):
        raise OSError("synthetic archive publish failure")

    monkeypatch.setattr(archive_json_io.os, failure, fail)
    function = getattr(native_archive, operation)
    args = (str(archive), "target")
    if operation == "update_file_global":
        args += ({"id": "target", "updated": True},)
    with pytest.raises(OSError, match="synthetic archive publish failure"):
        function(*args)

    assert archive.read_bytes() == raw
    assert "synthetic archive publish failure" in caplog.text
    assert len(list(tmp_path.glob("*.tmp"))) == 1


def test_legacy_archive_serialization_failure_does_not_truncate(
    tmp_path, caplog, native_archive
):
    archive = tmp_path / "archive.json"
    raw = b'[{"id":"target","evidence":"confirmed"}]'
    archive.write_bytes(raw)
    with pytest.raises(TypeError):
        native_archive.update_file_global(
            str(archive), "target", {"id": "target", "invalid": object()}
        )
    assert archive.read_bytes() == raw
    assert "Global file write failed" in caplog.text


@pytest.mark.parametrize("facade", [False, True])
@pytest.mark.parametrize("operation", ["update_file_global", "remove_item_from_json"])
def test_legacy_archive_write_preserves_unrelated_evidence(
    tmp_path, facade, operation, native_archive
):
    from src import server

    module = server if facade else native_archive
    archive = tmp_path / "archive.json"
    retained = {"id": "keep", "_raw_detail_artifacts": {"path": "keep.html"}}
    archive.write_text(json.dumps([{"id": "target"}, retained]), encoding="utf-8")
    function = getattr(module, operation)
    replacement = {"id": "target", "updated": True}
    args = (str(archive), "target")
    if operation == "update_file_global":
        args += (replacement,)
    function(*args)
    expected = (
        [replacement, retained] if operation == "update_file_global" else [retained]
    )
    assert json.loads(archive.read_text(encoding="utf-8")) == expected
    assert not list(tmp_path.glob("*.tmp"))

    confirmed = archive.read_bytes()
    args = (str(archive), "missing")
    if operation == "update_file_global":
        args += ({"id": "missing"},)
    function(*args)
    assert archive.read_bytes() == confirmed


@pytest.mark.parametrize("raw", [b'{"unfinished":', b"{}", b"[null]", b"null"])
def test_item_update_rejects_corrupt_or_wrong_shape_without_overwriting(
    tmp_path, raw, native_archive
):
    archive = tmp_path / "archive.json"
    archive.write_bytes(raw)
    with pytest.raises(ValueError):
        native_archive.update_item_in_json(str(archive), "new", {"id": "new"})
    assert archive.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [archive]


@pytest.mark.parametrize("failure", ["fsync", "replace"])
def test_failed_publish_preserves_confirmed_archive_and_pending_snapshot(
    tmp_path, monkeypatch, failure, native_archive
):
    archive = tmp_path / "archive.json"
    raw = b'[{"id":"old","evidence":"keep"}]'
    archive.write_bytes(raw)

    def fail(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(archive_json_io.os, failure, fail)
    with pytest.raises(OSError):
        native_archive.update_item_in_json(str(archive), "new", {"id": "new"})
    assert archive.read_bytes() == raw
    assert len(list(tmp_path.glob("*.tmp"))) == 1
    assert list(tmp_path.glob("*.json")) == [archive]


def test_successful_append_retains_other_archive_records(tmp_path, native_archive):
    archive = tmp_path / "archive.json"
    archive.write_text(
        '[{"id":"old","_raw_detail_artifacts":{"path":"keep.html"}}]', encoding="utf-8"
    )
    native_archive.update_item_in_json(str(archive), "new", {"id": "new"})
    assert json.loads(archive.read_text(encoding="utf-8")) == [
        {"id": "old", "_raw_detail_artifacts": {"path": "keep.html"}},
        {"id": "new"},
    ]


def test_location_handler_reports_failure_and_retains_corrupt_input(
    tmp_path, monkeypatch
):
    archive = tmp_path / "collected_locations.json"
    archive.write_bytes(b'[{"code":')
    monkeypatch.setattr(server_handler_analysis, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        server_handler_analysis, "_require_control_plane", lambda _: True, raising=False
    )
    monkeypatch.setattr(
        server_handler_analysis,
        "_read_json_body",
        lambda _: (True, {"locations": [{"code": "1", "name": "new"}]}),
        raising=False,
    )

    class Handler:
        def __init__(self):
            self.errors = []

        def send_error_json(self, **kwargs):
            self.errors.append(kwargs)

        def send_json(self, payload):
            pytest.fail("Corrupt archive was reported as saved")

    handler = Handler()
    server_handler_analysis._post_save_locations(handler)
    assert handler.errors[0]["status"] == 500
    assert archive.read_bytes() == b'[{"code":'


def test_concurrent_location_saves_preserve_both_requests(tmp_path, monkeypatch):
    archive = tmp_path / "collected_locations.json"
    archive.write_text('[{"code":"old","name":"Existing"}]', encoding="utf-8")
    monkeypatch.setattr(server_handler_analysis, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server_handler_analysis.RUNTIME, "file_lock", threading.Lock())
    monkeypatch.setattr(
        server_handler_analysis, "_require_control_plane", lambda _: True, raising=False
    )
    monkeypatch.setattr(
        server_handler_analysis,
        "_read_json_body",
        lambda handler: (True, {"locations": handler.locations}),
        raising=False,
    )
    first_read, second_read, release_first = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    read_records = archive_json_io.read_records

    def delayed_read(path):
        records = read_records(path)
        if not first_read.is_set():
            first_read.set()
            assert release_first.wait(5)
        else:
            second_read.set()
        return records

    monkeypatch.setattr(archive_json_io, "read_records", delayed_read)

    class Handler:
        def __init__(self, code):
            self.locations = [{"code": code, "name": code}]
            self.response = None

        def send_json(self, payload):
            self.response = payload

        def send_error_json(self, **error):
            pytest.fail(f"Location save failed: {error}")

    first, second = Handler("first"), Handler("second")
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(server_handler_analysis._post_save_locations, first)
        try:
            assert first_read.wait(2)
            two = pool.submit(server_handler_analysis._post_save_locations, second)
            # Without transaction serialization, force the second write to finish
            # before the stale first reader publishes its result.
            if second_read.wait(0.2):
                two.result(timeout=2)
        finally:
            release_first.set()
        one.result(timeout=2)
        two.result(timeout=2)
    assert first.response == second.response == {"status": "ok", "count": 1}
    saved = json.loads(archive.read_text(encoding="utf-8"))
    assert {row["code"]: row["name"] for row in saved} == {
        "old": "Existing",
        "first": "first",
        "second": "second",
    }
