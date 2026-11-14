"""The legacy editor reads journal evidence and cannot truncate newer records."""

from types import SimpleNamespace

from src import archive_json_io as io
from src import data_fixer_app_part_05 as editor


def test_editor_updates_journal_record_without_losing_other_rows(tmp_path):
    path = tmp_path / "archive.json"
    io.write_records(path, [{"id": "keep"}])
    io.append_journal(path, upserts=[{"id": "target", "title": "old"}])
    host = SimpleNamespace(log=lambda _: None)
    assert editor.DataFixerAppPart05.save_record(
        host, {"id": "target", "json_file": str(path)}, {"title": "new"}
    )
    rows = io.read_records(path)
    assert rows[0] == {"id": "keep"}
    assert rows[1]["title"] == "new"


def test_editor_detects_concurrent_publication(tmp_path, monkeypatch):
    path = tmp_path / "archive.json"
    io.write_records(path, [{"id": "target", "title": "old"}])
    logs = []
    host = SimpleNamespace(log=logs.append)
    normalize = editor.normalize_community_fields

    def concurrent(record):
        io.write_records(path, [{"id": "target", "title": "concurrent"}])
        normalize(record)

    monkeypatch.setattr(editor, "normalize_community_fields", concurrent)
    assert not editor.DataFixerAppPart05.save_record(
        host, {"id": "target", "json_file": str(path)}, {"title": "stale"}
    )
    assert io.read_records(path)[0]["title"] == "concurrent"
    assert any("其他写者" in line for line in logs)
