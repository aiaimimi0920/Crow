import json
from pathlib import Path

import pytest

from src.analysis.six_month.aggregate import aggregate_archives
from src.analysis.six_month.inputs import archive_candidate
from src.analysis.six_month.source_records import read_source_files


def test_worker_only_reads_completed_final_not_selected_or_extracted(tmp_path):
    item = tmp_path / "123"
    item.mkdir()
    final = {
        "id": 123,
        "is_processed": True,
        "城市": "北京市",
        "区": "测试区",
        "所属小区": "地段名未核",
        "交易时间": "2026-08-22",
        "是否成交": True,
        "成交价格": 1000000,
        "建筑面积": 100,
    }
    (item / "final.json").write_text(json.dumps(final), encoding="utf8")
    (item / "selected.json").write_text("not-json-incomplete", encoding="utf8")
    (item / "extracted.json").write_text("not-json-incomplete", encoding="utf8")
    before = (item / "final.json").read_bytes()
    files = list(read_source_files(tmp_path, "worker-final"))
    assert len(files) == 1
    assert files[0][1][0]["交易时间"] == "2026-08-22"
    report = aggregate_archives(tmp_path, "worker-final")
    assert report["community_months"][0]["month"] == "2026-08"
    assert report["location_resolution"].endswith("unverified")
    assert (item / "final.json").read_bytes() == before


def test_worker_unprocessed_skipped_and_id_mismatch_rejected(tmp_path):
    item = tmp_path / "123"
    item.mkdir()
    path = item / "final.json"
    path.write_text(json.dumps({"id": 123, "is_processed": False}), encoding="utf8")
    assert list(read_source_files(tmp_path, "worker-final")) == []
    path.write_text(json.dumps({"id": 999, "is_processed": True}), encoding="utf8")
    with pytest.raises(ValueError, match="disagree"):
        list(read_source_files(tmp_path, "worker-final"))


def test_source_modified_during_read_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "daily.json"
    path.write_text("[]", encoding="utf8")
    original = Path.read_bytes

    def changing_read(p):
        content = original(p)
        p.write_text("[{}]", encoding="utf8")
        return content

    monkeypatch.setattr(Path, "read_bytes", changing_read)
    with pytest.raises(ValueError, match="changed while reading"):
        list(read_source_files(tmp_path))


def test_text_location_is_not_assumed_nested_object():
    row = {
        "location": "城市地址",
        "property": "unknown",
        "auction": "unknown",
        "城市": "北京市",
        "建筑面积": 10,
        "成交价格": 1000,
    }
    assert archive_candidate(row, "source")["unit_price"] == 100


def test_nested_completed_final_identity_and_no_fake_sold(tmp_path):
    item = tmp_path / "123"
    item.mkdir()
    row = {
        "source": {"item_id": "123", "source_item_id": "platform-456"},
        "audit": {"is_processed": True},
        "auction": {"status": "done"},
    }
    path = item / "final.json"
    path.write_text(json.dumps(row), encoding="utf8")
    records = next(read_source_files(tmp_path, "worker-final"))[1]
    candidate = archive_candidate(records[0], "synthetic_schema_test")
    assert json.loads(candidate["record_id"]) == ["storage", "123"]
    assert candidate["sold"] is False
    assert candidate["property_id"] is None
    assert candidate["available_at"] is None
    row["is_processed"] = False
    path.write_text(json.dumps(row), encoding="utf8")
    assert list(read_source_files(tmp_path, "worker-final")) == []


@pytest.mark.parametrize(
    "row",
    [
        {"id": 123, "source": {"item_id": "999"}},
        {"source_item_id": "123", "source": {"source_item_id": "999"}},
    ],
)
def test_conflicting_same_namespace_ids_not_silently_selected(row):
    with pytest.raises(ValueError, match="conflicting item ID"):
        archive_candidate(row, "synthetic_schema_test")


def test_nested_source_id_fallback_without_asset_inference():
    candidate = archive_candidate({"source": {"source_item_id": "123"}}, "test")
    assert json.loads(candidate["record_id"]) == ["platform", "unknown", "123"]
    assert candidate["property_id"] is None


def test_storage_and_platform_id_collision_does_not_merge_aggregates(tmp_path):
    common = {
        "城市": "北京市",
        "区": "测试区",
        "所属小区": "合成小区",
        "交易时间": "2026-08-22",
        "是否成交": True,
        "成交价格": 1000000,
        "建筑面积": 100,
    }
    a = dict(common, id=123, source_item_id="999")
    b = dict(common, source={"source_item_id": "123"})
    assert (
        archive_candidate(a, "test")["record_id"]
        != archive_candidate(b, "test")["record_id"]
    )
    (tmp_path / "daily.json").write_text(json.dumps([a, b]), encoding="utf8")
    report = aggregate_archives(tmp_path)
    assert len(report["community_months"]) == 1
    assert report["community_months"][0]["n"] == 2


def test_flat_and_nested_storage_aliases_share_analysis_key():
    a = archive_candidate({"id": 123}, "a")
    b = archive_candidate({"source": {"item_id": "123"}}, "b")
    assert a["record_id"] == b["record_id"]
