from src.analysis.six_month.demo import demo_report
from src.analysis.six_month.rolling_summary import summarize_folds


def test_equal_fold_comparison_and_missing_labels():
    folds = [
        {
            "cutoff": "a",
            "status": "scored",
            "predictions": [
                {"actual": 100, "b": 120, "c": 110},
                {"actual": None, "b": 900, "c": 800},
            ],
        },
        {
            "cutoff": "b",
            "status": "scored",
            "predictions": [{"actual": 100, "b": 100, "c": 120}] * 3,
        },
        {"cutoff": "c", "status": "insufficient_training_or_test_data"},
    ]
    result = summarize_folds(folds, "b", "c", False)
    assert result["equal_fold_mean_mae_delta_yuan_sqm"] == 5
    assert result["scored_rows"] == 4
    assert result["unscored_prediction_rows"] == 1
    assert result["insufficient_data_folds"] == 1
    assert result["label_scoring_fraction_of_predictions"] == 0.8


def test_empty_is_not_zero_error_or_success():
    result = summarize_folds([], "b", "c", True)
    assert result["equal_fold_mean_mae_delta_yuan_sqm"] is None
    assert result["label_scoring_fraction_of_predictions"] is None
    assert result["comparison"] == "crow_model_vs_constant_calibration"


def test_multi_origin_demo_is_synthetic_and_mature_each_fold():
    report = demo_report()
    assert report["status"] == "SYNTHETIC_PIPELINE_TEST_ONLY"
    for mode in ("crow_only", "market_augmented"):
        rolling = report[mode]["temporal"]
        assert len(rolling["folds"]) == 3
        assert rolling["rolling_summary"]["scored_rows"] == 12
        for fold in rolling["folds"]:
            assert (
                fold["manifest"]["latest_training_label_available_at"] <= fold["cutoff"]
            )
        assert len(report[mode]["holdout"]["folds"]) == 1
