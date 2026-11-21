import json
from datetime import date, datetime

import pytest

from src.analysis.six_month import current_input
from src.analysis.six_month.inputs import archive_candidate


class FrozenClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 18, 12, tzinfo=tz)


def write_archive(path, dates):
    rows = [
        {
            "id": i,
            "城市": "北京市",
            "区": "测试区",
            "所属小区": "测试小区",
            "成交价格": 1000000,
            "建筑面积": 100,
            "单价": 10000,
            "交易时间": str(day),
            "是否成交": True,
        }
        for i, day in enumerate(dates, 1)
    ]
    path.write_text(json.dumps(rows), encoding="utf8")


def test_current_raw_inputs_produce_features_not_fabricated_predictions(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(current_input, "datetime", FrozenClock)
    path = tmp_path / "archive.json"
    write_archive(
        path,
        [date(2026, 7, d) for d in (1, 2, 3)] + [date(2026, 10, d) for d in (1, 2, 3)],
    )
    before = path.read_bytes()
    report = current_input.current_snapshot_report(tmp_path)
    assert report["status"] == "current_feature_preview_only"
    assert len(report["feature_candidates"]) == 1
    assert report["market_predictions"] == []
    assert report["origin"] == "2026-11-18"
    assert "unresolved" in report["identity_policy"]
    assert path.read_bytes() == before


def test_old_data_cannot_be_relabelled_current(tmp_path, monkeypatch):
    monkeypatch.setattr(current_input, "datetime", FrozenClock)
    write_archive(tmp_path / "archive.json", [date(2020, 1, d) for d in (1, 2, 3)])
    report = current_input.current_snapshot_report(tmp_path)
    assert report["status"] == "refused_no_recent_crow_history"
    assert report["feature_candidates"] == []
    assert report["latest_usable_auction_date"] == "2020-01-03"


@pytest.mark.parametrize(
    "price,area", [(float("inf"), 1), (1, float("inf")), (float("nan"), 1)]
)
def test_archive_candidate_rejects_non_finite_or_zero_unit_price(price, area):
    assert (
        archive_candidate({"成交价格": price, "建筑面积": area}, "test")["unit_price"]
        is None
    )


def test_missing_archive_path_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        current_input.current_snapshot_report(tmp_path / "missing")
