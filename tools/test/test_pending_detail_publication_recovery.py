"""A rejected JSON candidate with pending DB commit is recoverable, not terminal."""

import pytest

from src import archive_json_io as io
from src.collection.publication import (
    detail_publication,
    pending_marker,
    publish_record,
)
from tools.test.test_detail_commit_recovery import captured as _captured_fixture


@pytest.fixture
def captured(tmp_path, monkeypatch):
    yield from _captured_fixture.__wrapped__(tmp_path, monkeypatch)


def test_pending_rejected_archive_can_retry_from_json_working_item(
    captured, monkeypatch
):
    case = captured
    paths = []
    original_publish = case.app.host.update_item_in_json

    def publish(path, item_id, record):
        paths.append(path)
        return original_publish(path, item_id, record)

    def fail(*_args, **_kwargs):
        raise OSError("synthetic database outage")

    monkeypatch.setattr(type(case.adapter), "accepts_detail", lambda *_: False)
    monkeypatch.setattr(case.app.host, "update_item_in_json", publish)
    with monkeypatch.context() as patch:
        patch.setattr(case.repository, "upsert_flat_item", fail)
        case.app.host.process_single_file(str(case.html))
    path = paths[-1]
    assert pending_marker(path, case.item_id).exists()
    assert io.read_records(path)[0]["detail_fetch_status"] == "detail_rejected"
    monkeypatch.setattr(
        case.app.host,
        "_get_working_item",
        lambda *_: {
            "file_path": path,
            "data": io.read_records(path)[0],
            "cached": False,
        },
    )
    case.app.host.process_single_file(str(case.html))
    assert not pending_marker(path, case.item_id).exists()
    assert (
        case.repository.get_flat_item(case.item_id)["detail_fetch_status"]
        == "detail_rejected"
    )
    assert not case.html.exists()


def test_marker_write_failure_prevents_detail_effects(tmp_path, monkeypatch):
    effects = []

    def fail(*_args, **_kwargs):
        raise OSError("marker write unavailable")

    monkeypatch.setattr(io, "write_json", fail)
    with (
        pytest.raises(OSError),
        detail_publication(str(tmp_path / "records.json"), "one"),
    ):
        effects.append("json or database")
    assert effects == []


def test_marker_clear_failure_propagates_and_blocks_seed(tmp_path, monkeypatch):
    from pathlib import Path

    path = str(tmp_path / "records.json")
    marker = pending_marker(path, "one")
    original_unlink = Path.unlink

    def fail_marker(self, *args, **kwargs):
        if self == marker:
            raise OSError("marker removal unavailable")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_marker)
    with pytest.raises(OSError), detail_publication(path, "one"):
        pass
    effects = []
    with pytest.raises(RuntimeError, match="awaits database recovery"):
        publish_record(
            path,
            "one",
            {},
            "sniff_saved",
            None,
            persist=lambda *_: effects.append("db"),
            publish=lambda *_: effects.append("json"),
            seed=True,
        )
    assert effects == [] and marker.exists()


def test_other_item_success_does_not_clear_failed_item_marker(tmp_path):
    path = str(tmp_path / "records.json")
    with pytest.raises(OSError), detail_publication(path, "one"):
        raise OSError("database unavailable")
    with detail_publication(path, "two"):
        pass
    assert pending_marker(path, "one").exists()
    assert not pending_marker(path, "two").exists()
