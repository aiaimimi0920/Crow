import json
from dataclasses import asdict, replace
from datetime import date

import numpy as np
import pytest
from test_six_month import fixture_rows

from src.analysis.six_month.dataset import build_examples
from src.analysis.six_month.inference import predict_report, train_artifact
from src.analysis.six_month.models import fit
from src.analysis.six_month.persistence import decode_model, export_model


def write_rows(path, rows):
    payload = [dict(asdict(row), sold=True) for row in rows]
    path.write_text(json.dumps(payload, default=str), encoding="utf8")


def trained_fixture():
    examples = build_examples(
        fixture_rows(), [date(2022, 7, 31), date(2022, 10, 31), date(2023, 7, 31)]
    )
    train = [
        r
        for r in examples
        if r.group[0] == "北京" and r.label_available_at <= date(2023, 7, 31)
    ]
    test = [
        r for r in examples if r.group[0] == "上海" and r.origin == date(2023, 7, 31)
    ]
    return fit(train, date(2023, 7, 31)), test


def test_json_roundtrip_preserves_predictions():
    model, rows = trained_fixture()
    restored = decode_model(json.loads(json.dumps(export_model(model, "test-hash"))))
    np.testing.assert_allclose(
        model.predict(rows), restored.predict(rows), rtol=0, atol=0
    )


def test_finite_model_coefficients_cannot_emit_zero_prices():
    model, rows = trained_fixture()
    artifact = export_model(model, "test-hash")
    artifact["coefficients"] = [-1000.0] + [0.0] * len(model.feature_names)
    restored = decode_model(artifact)
    with pytest.raises(ValueError, match="non-positive"):
        restored.predict(rows)


@pytest.mark.parametrize(
    "change",
    [
        {"feature_names": ["untrusted_feature"]},
        {"scale": [0]},
        {"coefficients": [float("nan")]},
        {"training_cities": ["上海"]},
        {"synthetic": "false"},
        {"trained_rows": -1},
        {"backend": "pickle"},
    ],
)
def test_invalid_model_artifacts_are_rejected(change):
    model, _ = trained_fixture()
    payload = dict(export_model(model, "test-hash"), **change)
    with pytest.raises((ValueError, TypeError)):
        decode_model(payload)


def test_train_then_predict_without_any_resale_input(tmp_path):
    source, auction_input, model_path = (
        tmp_path / n for n in ("train.json", "auctions.json", "model.json")
    )
    rows = fixture_rows()
    write_rows(source, rows)
    artifact = train_artifact(
        source, [date(2022, 7, 31), date(2022, 10, 31)], date(2023, 7, 31)
    )
    assert artifact["training_cities"] == ["北京"]
    model_path.write_text(json.dumps(artifact), encoding="utf8")
    auctions = [r for r in rows if r.kind == "auction"]
    write_rows(auction_input, auctions)
    report = predict_report(model_path, auction_input, date(2023, 7, 31))
    assert report["evidence"] == "synthetic_pipeline_test_only"
    assert report["ordinary_resale_input_required"] is False
    assert len(report["predictions"]) == 2
    write_rows(auction_input, [replace(r, synthetic=False) for r in auctions])
    with pytest.raises(ValueError, match="synthetic"):
        predict_report(model_path, auction_input, date(2023, 7, 31))


def test_model_cannot_train_without_mature_true_target(tmp_path):
    path = tmp_path / "auctions.json"
    write_rows(path, [r for r in fixture_rows() if r.kind == "auction"])
    with pytest.raises(ValueError, match="no mature ordinary resale"):
        train_artifact(path, [date(2022, 7, 31)], date(2023, 7, 31))


def test_prediction_rejects_labels_and_pretraining_dates(tmp_path):
    model, _ = trained_fixture()
    model_path, data_path = tmp_path / "model.json", tmp_path / "data.json"
    model_path.write_text(json.dumps(export_model(model, "test-hash")), encoding="utf8")
    write_rows(data_path, fixture_rows())
    with pytest.raises(ValueError, match="auctions only"):
        predict_report(model_path, data_path, date(2023, 7, 31))
    write_rows(data_path, [r for r in fixture_rows() if r.kind == "auction"])
    with pytest.raises(ValueError, match="precedes"):
        predict_report(model_path, data_path, date(2020, 1, 1))
