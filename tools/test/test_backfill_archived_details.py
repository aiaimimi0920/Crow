import json
from pathlib import Path

import pytest

from src.collection import detail_backfill as archived_detail_module
from src.storage.repository import DatabaseSettings, PropertyRepository
from tools.backfill_archived_details import backfill_archived_details


def _make_repo(tmp_path: Path) -> PropertyRepository:
    db_path = tmp_path / "archived-detail.sqlite3"
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def test_backfill_archived_details_updates_coordinates_from_archived_html(
    tmp_path: Path,
):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    detail_dir = data_root / "html_archive" / "2026" / "2026-03-01"
    archive_dir.mkdir(parents=True, exist_ok=True)
    detail_dir.mkdir(parents=True, exist_ok=True)

    detail_file = detail_dir / "item-1.html"
    detail_file.write_text(
        "<html><script>var center=[121.5001,31.2002];</script></html>",
        encoding="utf-8",
    )

    data_file = archive_dir / "2026-03-01.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "交易时间": "2026-03-01 10:00:00",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                    "detail_archive_path": "html_archive/2026/2026-03-01/item-1.html",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = backfill_archived_details(
        data_root, limit=10, dry_run=False, extract_risk=False
    )

    assert report["updated_records"] == 1
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    assert payload[0]["latitude"] == 31.2002
    assert payload[0]["longitude"] == 121.5001
    assert payload[0]["coordinate_backfill_strategy"] == "archived_detail_html"
    assert (data_root / payload[0]["detail_text_path"]).is_file()
    assert Path(payload[0]["detail_text_path"]).name == "item-1.txt"


def test_backfill_archived_details_can_use_db_candidates_with_source_json_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    detail_dir = data_root / "html_archive" / "2026" / "2026-03-01"
    archive_dir.mkdir(parents=True, exist_ok=True)
    detail_dir.mkdir(parents=True, exist_ok=True)

    detail_file = detail_dir / "item-2.html"
    detail_file.write_text(
        "<html><script>var center=[121.6001,31.3002];</script></html>",
        encoding="utf-8",
    )

    data_file = archive_dir / "2026-03-01.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": 2,
                    "交易时间": "2026-03-01 10:00:00",
                    "成交价格": "120万",
                    "起拍价格": "90万",
                    "建筑面积": "88㎡",
                    "detail_archive_path": "html_archive/2026/2026-03-01/item-2.html",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        {
            "id": 2,
            "交易时间": "2026-03-01 10:00:00",
            "成交价格": "120万",
            "起拍价格": "90万",
            "建筑面积": "88㎡",
            "detail_archive_path": "html_archive/2026/2026-03-01/item-2.html",
        },
        event_type="seed",
        event_payload={"source_file": str(data_file)},
    )

    monkeypatch.setattr(
        archived_detail_module,
        "create_collection_repository_from_env",
        lambda **_: repo,
    )
    monkeypatch.setattr(
        archived_detail_module,
        "_iter_rows",
        lambda _root: (_ for _ in ()).throw(
            AssertionError("fallback scan should not be used")
        ),
    )

    report = backfill_archived_details(
        data_root, limit=10, dry_run=False, extract_risk=False
    )

    assert report["updated_records"] == 1
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    assert payload[0]["latitude"] == 31.3002
    assert payload[0]["longitude"] == 121.6001
    db_item = repo.get_flat_item("2")
    assert db_item is not None
    assert db_item["latitude"] == 31.3002
    assert db_item["longitude"] == 121.6001


def test_backfill_archived_details_generates_sidecar_artifacts_from_existing_archive(
    tmp_path: Path,
):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    detail_dir = data_root / "html_archive" / "2026" / "2026-03-01"
    archive_dir.mkdir(parents=True, exist_ok=True)
    detail_dir.mkdir(parents=True, exist_ok=True)

    detail_file = detail_dir / "item-3.html"
    detail_file.write_text(
        '<html><div id="J_NoticeDetail">测试公告正文</div><a href="https://example.com/report.pdf">评估报告</a></html>',
        encoding="utf-8",
    )

    data_file = archive_dir / "2026-03-01.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": 3,
                    "交易时间": "2026-03-01 10:00:00",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                    "detail_archive_path": "html_archive/2026/2026-03-01/item-3.html",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = backfill_archived_details(
        data_root, limit=10, dry_run=False, extract_risk=False
    )

    assert report["updated_records"] == 1
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    assert (data_root / payload[0]["notice_text_path"]).is_file()
    assert (data_root / payload[0]["attachment_manifest_path"]).is_file()
    assert Path(payload[0]["notice_text_path"]).name == "item-3.notice.txt"
    assert (
        Path(payload[0]["attachment_manifest_path"]).name == "item-3.attachments.json"
    )
