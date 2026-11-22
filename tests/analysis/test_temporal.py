from dataclasses import replace
from datetime import date

import pytest

from src.analysis.six_month.dataset import AUCTION_FEATURES, BASE_FEATURES, Example
from src.analysis.six_month.evaluation import backtest
from src.analysis.six_month.models import fit


def rows():
    train = Example(
        ("北京", "区", "合成小区"),
        date(2022, 7, 31),
        "2023-01",
        10000,
        {key: 0.0 for key in BASE_FEATURES + AUCTION_FEATURES},
        11000,
        date(2023, 2, 1),
        True,
        (),
        3,
        "crow_only",
        {},
    )
    test = replace(
        train,
        origin=date(2023, 7, 31),
        target_month="2024-01",
        label_available_at=date(2024, 2, 1),
    )
    return train, test


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"target_month": "2022-08"}, "six calendar"),
        ({"label_available_at": date(2022, 8, 1)}, "full target month"),
        ({"target": float("nan")}, "finite and positive"),
        ({"baseline": 0}, "finite and positive"),
    ],
)
def test_direct_fit_rejects_forged_temporal_contract(change, reason):
    train, _ = rows()
    with pytest.raises(ValueError, match=reason):
        fit([replace(train, **change)], date(2023, 7, 31))


def test_backtest_rejects_duplicate_weighting():
    train, test = rows()
    with pytest.raises(ValueError, match="duplicate"):
        backtest([train, train, test], [test.origin], evaluation_asof=date(2024, 2, 1))


def test_fold_manifest_and_unavailable_score():
    train, test = rows()
    cutoff = test.origin
    report = backtest([train, test], [cutoff], evaluation_asof=date(2024, 1, 31))
    fold = report["folds"][0]
    assert fold["status"] == "predictions_only_labels_unavailable"
    assert fold["predictions"][0]["actual"] is None
    assert fold["manifest"]["latest_training_label_available_at"] == "2023-02-01"
    assert fold["manifest"]["training_cities"] == ["北京"]
    later = backtest([test, train], [cutoff], evaluation_asof=date(2024, 2, 1))[
        "folds"
    ][0]
    assert later["manifest"] == fold["manifest"]
    assert later["status"] == "scored"
    assert report["evidence"] == "synthetic_pipeline_test_only"
