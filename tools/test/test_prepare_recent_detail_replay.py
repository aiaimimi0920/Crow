import json
from pathlib import Path

import pytest

from src.collection import detail_replay as replay_module
from src.storage.repository import DatabaseSettings, PropertyRepository
from tools.prepare_recent_detail_replay import prepare_recent_detail_replay


def _make_repo(tmp_path: Path) -> PropertyRepository:
    db_path = tmp_path / "detail-replay.sqlite3"
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def test_prepare_recent_detail_replay_marks_candidates_for_refetch(tmp_path: Path):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    data_file = archive_dir / "2026-03-05.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": 1001,
                    "交易时间": "2026-03-05 10:00:00",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                    "detail_captured": True,
                    "原始网站": "https://sf-item.taobao.com/sf_item/1001.htm",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        {
            "id": 1001,
            "交易时间": "2026-03-05 10:00:00",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "detail_captured": True,
            "原始网站": "https://sf-item.taobao.com/sf_item/1001.htm",
        },
        event_type="seed",
        event_payload={"source_file": str(data_file)},
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        replay_module, "create_collection_repository_from_env", lambda **_: repo
    )
    try:
        report = prepare_recent_detail_replay(
            data_root=data_root, window_days=7, limit=10, dry_run=False
        )
    finally:
        monkeypatch.undo()

    assert report["prepared_count"] == 1
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    assert payload[0]["is_processed"] is False
    assert payload[0]["url"] == "https://sf-item.taobao.com/sf_item/1001.htm"
    assert payload[0]["detail_replay_reason"] == "missing_enrich_fields"
    db_item = repo.get_flat_item("1001")
    assert db_item is not None
    assert db_item["url"] == "https://sf-item.taobao.com/sf_item/1001.htm"
    assert db_item["is_processed"] is False


def test_prepare_recent_detail_replay_can_fallback_to_item_url_without_original_url(
    tmp_path: Path,
):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    data_file = archive_dir / "2026-03-05.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": 2002,
                    "交易时间": "2026-03-05 10:00:00",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                    "是否成交": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = prepare_recent_detail_replay(
        data_root=data_root, window_days=7, limit=10, dry_run=False
    )

    assert report["prepared_count"] == 1
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    assert payload[0]["url"] == "https://sf-item.taobao.com/sf_item/2002.htm"
