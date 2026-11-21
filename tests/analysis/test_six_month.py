import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from src.analysis.six_month.__main__ import safe_output
from src.analysis.six_month.contracts import (
    Transaction,
    add_months,
    unique_transactions,
)
from src.analysis.six_month.dataset import build_examples
from src.analysis.six_month.evaluation import backtest
from src.analysis.six_month.inputs import archive_candidate, audit_archives
from src.analysis.six_month.models import fit


def fixture_rows():
    rows = []
    for city in ("北京", "上海"):
        for m in range(36):
            month = add_months(date(2022, 1, 1), m)
            for kind in ("resale", "auction"):
                for i in range(3):
                    day = month.replace(day=i + 2)
                    rid = f"{city}-{kind}-{m}-{i}"
                    rows.append(
                        Transaction(
                            rid,
                            rid,
                            kind,
                            city,
                            "区",
                            "已核实小区",
                            "2室",
                            day,
                            day,
                            (10000 + m * 30 + i * 10)
                            * (0.8 if kind == "auction" else 1),
                            "synthetic_fixture",
                            True,
                        )
                    )
    return rows


def examples():
    return build_examples(
        fixture_rows(),
        [date(2022, 7, 31), date(2022, 10, 31), date(2023, 7, 31)],
        input_mode="market_augmented",
    )


def test_calendar_not_180_days():
    assert add_months(date(2023, 8, 31), 6) == date(2024, 2, 29)


def test_future_or_late_published_data_does_not_change_features():
    rows = fixture_rows()
    origin = date(2022, 7, 31)
    before = build_examples(rows, [origin])
    rows = [replace(r, unit_price=9e9) if r.traded_at > origin else r for r in rows]
    late = replace(
        rows[0],
        record_id="late",
        property_id="late",
        available_at=date(2025, 1, 1),
        unit_price=9e9,
    )
    after = build_examples(rows + [late], [origin])
    assert [e.features for e in before] == [e.features for e in after]
    assert [e.baseline for e in before] == [e.baseline for e in after]


def test_fit_rejects_holdout_and_immature_labels():
    ex = examples()
    with pytest.raises(ValueError, match="training cities"):
        fit(ex, date(2023, 7, 31))
    with pytest.raises(ValueError, match="mature"):
        fit([next(r for r in ex if r.group[0] == "北京")], date(2022, 8, 1))


def test_training_only_standardization_and_forecast():
    ex = examples()
    train = [
        r
        for r in ex
        if r.group[0] == "北京" and r.label_available_at <= date(2023, 7, 31)
    ]
    model = fit(train, date(2023, 7, 31))
    test = [r for r in ex if r.group[0] == "上海" and r.origin == date(2023, 7, 31)]
    assert len(model.predict(test)) == 1
    with pytest.raises(ValueError, match="precedes"):
        model.predict([replace(test[0], origin=date(2020, 1, 1))])


def test_backtest_and_holdout_are_separate_and_marked_synthetic():
    ex = examples()
    report = backtest(ex, [date(2023, 7, 31)], evaluation_asof=date(2024, 2, 1))
    assert report["evidence"] == "synthetic_pipeline_test_only"
    assert {p["group"][0] for p in report["folds"][0]["predictions"]} == {"北京"}
    final = backtest(
        ex, [date(2023, 7, 31)], holdout=True, evaluation_asof=date(2024, 2, 1)
    )
    assert {p["group"][0] for p in final["folds"][0]["predictions"]} == {"上海"}
    assert final["folds"][0]["scores"]["no_change"]["n"] == 1


def test_labels_not_scored_before_full_target_month():
    report = backtest(
        examples(), [date(2023, 7, 31)], evaluation_asof=date(2024, 1, 15)
    )
    assert report["folds"][0]["scores"]["no_change"]["n"] == 0


def test_duplicates_and_conflicts():
    row = fixture_rows()[0]
    assert unique_transactions([row, row]) == [row]
    with pytest.raises(ValueError, match="conflicting"):
        unique_transactions([row, replace(row, unit_price=1)])


def test_archive_never_certifies_missing_or_default_fields(tmp_path):
    raw = {
        "id": 1,
        "城市": "北京市",
        "成交价格": 100,
        "建筑面积": 10,
        "是否成交": True,
        "property": {"ownership_share_ratio": 1.0},
    }
    candidate = archive_candidate(raw, "fixture.json")
    assert candidate["unit_price"] == 10
    assert candidate["available_at"] is None
    assert candidate["full_ownership"] is None
    with pytest.raises(ValueError, match="missing"):
        Transaction.from_dict(candidate)
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps([raw]), encoding="utf-8")
    before = path.read_bytes()
    report = audit_archives(tmp_path)
    assert report["city_rows"] == {"北京": 1}
    assert path.read_bytes() == before


def test_output_cannot_write_collector_or_overwrite():
    with pytest.raises(ValueError, match="artifacts/analysis"):
        safe_output(str(Path("datas/archive/result.json")))


def test_unknown_cell_not_filled_with_city_price():
    rows = [
        replace(r, community="孤立") if r.kind == "auction" else r
        for r in fixture_rows()
    ]
    result = build_examples(rows, [date(2022, 7, 31)], input_mode="market_augmented")
    assert all(r.features["auction_missing"] == 1 for r in result)


def test_mixed_synthetic_and_real_rejected():
    rows = fixture_rows()
    with pytest.raises(ValueError, match="mix"):
        build_examples(rows + [replace(rows[0], synthetic=False)], [date(2022, 7, 31)])


def test_cross_id_mixed_provenance_rejected_in_both_orders():
    row = fixture_rows()[0]
    other = replace(row, record_id="different", synthetic=False)
    for rows in ([row, other], [other, row]):
        with pytest.raises(ValueError, match="mix"):
            unique_transactions(rows)


def test_crow_inputs_do_not_depend_on_resale_history():
    rows = fixture_rows()
    origin = date(2022, 7, 31)
    before = build_examples(rows, [origin])
    altered = [
        replace(r, unit_price=9999999) if r.kind == "resale" else r for r in rows
    ]
    after = build_examples(altered, [origin])
    assert [r.features for r in before] == [r.features for r in after]
    assert [r.baseline for r in before] == [r.baseline for r in after]
    assert all(r.input_mode == "crow_only" for r in before)


def test_unknown_layout_and_use_are_accepted():
    from dataclasses import asdict

    row = asdict(fixture_rows()[0])
    row.update(sold=True, house_type=None, residential=None, full_ownership=None)
    parsed = Transaction.from_dict(row)
    assert parsed.house_type == ""
    assert len(parsed.group) == 3
    row["residential"] = False
    with pytest.raises(ValueError, match="non-residential"):
        Transaction.from_dict(row)


def test_crow_model_rejects_different_input_contract():
    ex = examples()
    train = [
        r
        for r in ex
        if r.group[0] == "北京" and r.label_available_at <= date(2023, 7, 31)
    ]
    model = fit(train, date(2023, 7, 31))
    with pytest.raises(ValueError, match="input mode"):
        model.predict(
            [replace(ex[0], origin=date(2023, 7, 31), input_mode="crow_only")]
        )


def test_real_aggregation_retains_unknown_use_and_separates_bad_prices(tmp_path):
    from src.analysis.six_month.aggregate import aggregate_archives

    base = {
        "id": 1,
        "城市": "北京市",
        "区": "测试区",
        "所属小区": "测试小区",
        "成交价格": 1000000,
        "建筑面积": 100,
        "交易时间": "2022-01-01",
        "是否成交": True,
    }
    rows = [base, dict(base, id=2, 单价=1), dict(base, id=3, 房屋用途="商铺")]
    path = tmp_path / "archive.json"
    path.write_text(json.dumps(rows), encoding="utf8")
    before = path.read_bytes()
    report = aggregate_archives(tmp_path)
    assert report["community_months"][0]["n"] == 1
    assert report["skipped"]["price_area_unit_inconsistent"] == 1
    assert report["skipped"]["explicit_non_residential"] == 1
    assert path.read_bytes() == before


def test_holdout_preflight_failure_does_not_consume_receipt(tmp_path, monkeypatch):
    from src.analysis.six_month import __main__ as cli
    from src.analysis.six_month.contracts import SPLIT_VERSION

    source = tmp_path / "input.json"
    source.write_text("[]", encoding="utf8")
    protocol = tmp_path / "protocol.json"
    protocol.write_text(
        json.dumps(
            {
                "split_version": SPLIT_VERSION,
                "backend": "ridge",
                "cutoffs": "2023-07-31",
                "input_mode": "crow_only",
                "label_definition": "resale_cell_median_month_t_plus_6_v1",
            }
        ),
        encoding="utf8",
    )
    monkeypatch.setattr(cli, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "six_month",
            "evaluate",
            "--input",
            str(source),
            "--origins",
            "2023-07-31",
            "--cutoffs",
            "2023-07-31",
            "--as-of",
            "2024-02-01",
            "--holdout",
            "--frozen-protocol",
            str(protocol),
            "--output",
            str(tmp_path / "result.json"),
        ],
    )
    with pytest.raises(ValueError, match="preflight"):
        cli.main()
    assert not (tmp_path / "real-holdout-receipt.json").exists()
