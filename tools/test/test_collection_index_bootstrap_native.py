"""Live bootstrap dependencies and non-destructive interrupted-file recovery."""

import os
from types import SimpleNamespace

import pytest

from src.collection_index_bootstrap import CollectionIndexBootstrap
from src.runtime_state import RuntimeState


@pytest.fixture(params=[False, True])
def host(request):
    from src import server, server_data_runtime

    return server if request.param else server_data_runtime


def test_saved_index_loader_follows_root_runtime_and_repository(
    host, tmp_path, monkeypatch
):
    load = host.load_data
    assert isinstance(load.__self__, CollectionIndexBootstrap)
    if host.__name__ == "src.server":
        assert host._CONTEXT.load_data is load
    for index in range(2):
        root = tmp_path / str(index)
        root.mkdir()
        (root / "record.json").write_text(
            '[{"id":"fresh","status":"done"}]', encoding="utf-8"
        )
        runtime = RuntimeState()
        pending = runtime.collection.pending_tasks
        monkeypatch.setattr(host, "DATA_DIR", root)
        monkeypatch.setattr(host, "RUNTIME", runtime)
        monkeypatch.setattr(host, "DB_REPOSITORY", SimpleNamespace(enabled=False))
        monkeypatch.setattr(host, "sync_collection_record", lambda _item: None)
        load()
        assert runtime.collection.pending_tasks is pending
        assert pending == ["fresh"]
        assert runtime.collection.seen_ids["fresh"]["data"]["id"] == "fresh"


def test_saved_orphan_recovery_preserves_evidence_and_old_markers(
    host, tmp_path, monkeypatch
):
    recover = host.cleanup_orphaned_files
    assert isinstance(recover.__self__, CollectionIndexBootstrap)
    for index in range(2):
        root = tmp_path / str(index)
        root.mkdir()
        monkeypatch.setattr(host, "DATA_DIR", root)
        (root / "item-a.html.processing.failed").write_bytes(b"failed evidence")
        (root / "item-b.html.processing").write_bytes(b"interrupted evidence")
        (root / "item-old.html.failed").write_bytes(b"existing marker")
        recover()
        assert (root / "item-a.html").read_bytes() == b"failed evidence"
        assert (root / "item-a.html.failed").read_text() == "recovered"
        assert (root / "item-b.html").read_bytes() == b"interrupted evidence"
        assert (root / "item-old.html.failed").read_bytes() == b"existing marker"
        assert not list(root.glob("*.processing*"))


def test_orphan_rename_failure_is_logged_and_other_files_recover(
    host, tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(host, "DATA_DIR", tmp_path)
    failed = tmp_path / "blocked.processing.failed"
    failed.write_bytes(b"keep")
    (tmp_path / "ready.processing").write_bytes(b"ready")

    def rename(source, target):
        if source == str(failed):
            raise OSError("isolated rename failure")
        os.rename(source, target)

    monkeypatch.setattr(host, "os", SimpleNamespace(path=os.path, rename=rename))
    host.cleanup_orphaned_files()
    assert failed.read_bytes() == b"keep"
    assert not (tmp_path / "blocked.failed").exists()
    assert (tmp_path / "ready").read_bytes() == b"ready"
    assert "isolated rename failure" in caplog.text
