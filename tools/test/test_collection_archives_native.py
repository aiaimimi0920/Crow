"""Native archive naming, publication and live facade dependencies."""

import datetime
import json
from pathlib import Path

from src.collection_archive_paths import CollectionArchivePaths
from src.collection_archive_records import CollectionArchiveRecords


def test_archive_exports_share_native_context_identity():
    from src import server

    for owner in (CollectionArchivePaths, CollectionArchiveRecords):
        for name in owner.__all__:
            method = getattr(server, name)
            assert isinstance(method.__self__, owner)
            assert getattr(server._CONTEXT, name) is method


def test_saved_archive_paths_follow_data_root_and_preserve_names(tmp_path, monkeypatch):
    from src import server

    data_path = server.get_data_path
    list_path = server.get_list_payload_archive_path
    moment = datetime.datetime(2026, 9, 25, 12, 34, 56, 123456)  # noqa: DTZ001 - preserve local wall-clock archive naming.
    for name in ("first", "replacement"):
        root = tmp_path / name
        monkeypatch.setattr(server, "DATA_DIR", str(root))
        assert (
            Path(data_path("2026-09-25T12:00:00"))
            == root / "archive/2026/2026-09-25.json"
        )
        assert (
            Path(list_path(moment, "json"))
            == root
            / "list_payload_archive/2026/2026-09-25/list-20260925-123456-123456.json"
        )
        assert list_path(moment, ".html").endswith("-123456.html")
        assert (root / "archive/2026").is_dir()


def test_saved_raw_archive_uses_replaced_path_and_returns_relative_evidence(
    tmp_path, monkeypatch
):
    from src import server

    archive = server.archive_list_payload
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    for empty in (None, "", []):
        assert archive(empty) is None
    assert list(tmp_path.iterdir()) == []
    target = tmp_path / "chosen.json"
    calls = []

    def choose(captured_at, suffix):
        calls.append((captured_at, suffix))
        return str(target)

    monkeypatch.setattr(server, "get_list_payload_archive_path", choose)
    payload = {"title": "归档证据"}
    assert archive(payload, "capture") == "chosen.json"
    assert calls == [("capture", ".json")]
    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert "归档证据" in target.read_text(encoding="utf-8")


def test_saved_detail_helpers_use_replaced_shared_adapter(tmp_path, monkeypatch):
    from src import server

    path = server.get_detail_archive_path
    extract = server._extract_detail_artifacts
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(
        server,
        "_shared_get_detail_archive_path",
        lambda *args: calls.append(args) or tmp_path / "detail.html",
    )
    monkeypatch.setattr(
        server, "_shared_extract_detail_artifacts", lambda **kwargs: kwargs
    )
    assert path("date", "item", ".html") == str(tmp_path / "detail.html")
    assert calls == [(str(tmp_path), "date", "item", ".html")]
    assert extract("html", "item", "date", "url") == {
        "data_root": str(tmp_path),
        "html_content": "html",
        "item_id": "item",
        "auction_date": "date",
        "source_url": "url",
    }
