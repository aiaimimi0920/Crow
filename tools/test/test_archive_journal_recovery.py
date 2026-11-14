"""Existing journal generations must not undo a later committed mutation."""

import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src import archive_json_io as io
from src.archive_transaction import archive_transaction
from src.collection_archive_records import CollectionArchiveRecords
from src.runtime_state import RuntimeState


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_existing_journal_cannot_undo_latest_mutation(tmp_path, operation):
    path = tmp_path / "records.json"
    io.write_records(path, [{"id": "keep"}])
    io.append_journal(path, upserts=[{"id": "target", "value": "old"}])
    runtime = RuntimeState()
    store = CollectionArchiveRecords(lambda: runtime, os.path.exists, io.read_records)
    if operation == "update":
        store.update_item_in_json(path, "target", {"id": "target", "value": "new"})
        assert io.read_records(path)[1]["value"] == "new"
    else:
        store.remove_item_from_json(path, "target")
        assert io.read_records(path) == [{"id": "keep"}]


@pytest.mark.parametrize(
    "raw", [b'{"u":', b"[]\n", b'{"u":{"id":"\xff"}}\n', b'{"unknown":1}\n']
)
def test_corrupt_journal_is_preserved_and_blocks_publication(tmp_path, raw):
    path = tmp_path / "records.json"
    io.write_records(path, [{"id": "keep"}])
    before = path.read_bytes()
    io.journal_path(path).write_bytes(raw)
    with pytest.raises(ValueError):
        io.write_records(path, [{"id": "replacement"}])
    assert path.read_bytes() == before
    assert io.journal_path(path).read_bytes() == raw


def test_failed_journal_retirement_never_publishes_new_generation(
    tmp_path, monkeypatch
):
    path = tmp_path / "records.json"
    io.write_records(path, [{"id": "keep"}])
    io.append_journal(path, upserts=[{"id": "target", "value": "old"}])

    def fail(_path):
        raise PermissionError("journal locked")

    monkeypatch.setattr(io, "_truncate_journal", fail)
    with pytest.raises(PermissionError):
        io.write_records(path, [{"id": "target", "value": "new"}])
    assert io.read_records(path) == [{"id": "keep"}, {"id": "target", "value": "old"}]


def test_append_cannot_be_erased_during_compaction(tmp_path, monkeypatch):
    path = tmp_path / "records.json"
    io.write_records(path, [{"id": "keep"}])
    io.append_journal(path, upserts=[{"id": "old"}])
    entered, release, attempted = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    write = io.write_json

    def blocked_write(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return write(*args, **kwargs)

    monkeypatch.setattr(io, "write_json", blocked_write)

    def append():
        attempted.set()
        io.append_journal(path, upserts=[{"id": "new"}])

    with ThreadPoolExecutor(max_workers=2) as pool:
        compact = pool.submit(io.compact, path)
        assert entered.wait(5)
        pending = pool.submit(append)
        assert attempted.wait(5)
        release.set()
        compact.result(timeout=5)
        pending.result(timeout=5)
    assert {row["id"] for row in io.read_records(path)} == {"keep", "old", "new"}


def test_archive_transaction_excludes_another_process(tmp_path):
    path = tmp_path / "records.json"
    io.write_records(path, [{"id": "keep"}])
    code = (
        "import sys; from src.archive_json_io import append_journal; "
        "print('ready', flush=True); "
        "append_journal(sys.argv[1], upserts=[{'id': 'child'}])"
    )
    with archive_transaction(path):
        child = subprocess.Popen(
            [sys.executable, "-c", code, str(path)],
            cwd=Path(__file__).resolve().parents[2],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert child.stdout.readline().strip() == "ready"
        assert child.poll() is None
    stdout, stderr = child.communicate(timeout=15)
    assert child.returncode == 0, stdout + stderr
    assert io.read_records(path) == [{"id": "keep"}, {"id": "child"}]
