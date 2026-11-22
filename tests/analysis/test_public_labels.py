import json
from datetime import date

import pytest
from openpyxl import Workbook

from src.analysis.six_month.public_labels import read_wuhan_labels, readiness_report

HEADER = (
    "城市",
    "小区名称",
    "室",
    "厅",
    "室厅",
    "面积",
    "装修情况",
    "成交日期",
    "总价",
    "成交价格",
)


def workbook(path, rows):
    book = Workbook()
    book.active.append(HEADER)
    for row in rows:
        book.active.append(row)
    book.save(path)
    book.close()


def test_wuhan_readiness_does_not_backdate_or_merge_ambiguous_names(tmp_path):
    path = tmp_path / "source.xlsx"
    workbook(
        path,
        [
            ("武汉市", "甲小区", 2, 1, 3, 100, 1, date(2020, 5, 5), 100, 10000),
            ("武汉市", "乙小区", 2, 1, 3, 100, 1, date(2020, 5, 5), 100, 10000),
            (None, None),
        ],
    )
    archive = tmp_path / "aggregation.json"
    rows = [
        {"city": "武汉", "district": d, "community": name, "month": "2019-11", "n": 3}
        for name, d in (("甲小区", "一区"), ("乙小区", "一区"), ("乙小区", "二区"))
    ]
    rows.append(
        {
            "city": "上海",
            "district": "不可使用",
            "community": "甲小区",
            "month": "2019-11",
            "n": 999,
        }
    )
    archive.write_text(json.dumps({"community_months": rows}), encoding="utf8")
    before = path.read_bytes()
    report = readiness_report(path, archive)
    assert report["label_rows"] == 2
    assert report["single_crow_district_name_candidates"] == 1
    assert report["six_month_pairs_before_verified_entity_linkage"] == 1
    assert report["earliest_known_training_label_availability"] == "2021-04-27"
    assert (
        report["strict_historical_walkforward_possible_from_this_snapshot_alone"]
        is False
    )
    assert path.read_bytes() == before


def test_source_schema_change_fails_closed(tmp_path):
    path = tmp_path / "changed.xlsx"
    book = Workbook()
    book.active.append(["wrong columns"])
    book.save(path)
    book.close()
    with pytest.raises(ValueError, match="schema changed"):
        read_wuhan_labels(path)
