"""Descriptive paired comparison, not independent-observation significance."""

from statistics import mean


def summarize_folds(folds, baseline_key, model_key, crow_only):
    comparisons = []
    predicted = scored = 0
    for fold in folds:
        rows = fold.get("predictions", [])
        predicted += len(rows)
        valid = [r for r in rows if r["actual"] is not None]
        scored += len(valid)
        if not valid:
            continue
        baseline_error = mean(abs(r[baseline_key] - r["actual"]) for r in valid)
        model_error = mean(abs(r[model_key] - r["actual"]) for r in valid)
        comparisons.append(
            {
                "cutoff": fold["cutoff"],
                "paired_scored_rows": len(valid),
                "baseline_mae_yuan_sqm": baseline_error,
                "model_mae_yuan_sqm": model_error,
                "model_minus_baseline_mae_yuan_sqm": model_error - baseline_error,
            }
        )
    return {
        "requested_unique_folds": len(folds),
        "predicted_rows": predicted,
        "scored_rows": scored,
        "unscored_prediction_rows": predicted - scored,
        "insufficient_data_folds": sum(
            f["status"] == "insufficient_training_or_test_data" for f in folds
        ),
        "label_scoring_fraction_of_predictions": scored / predicted
        if predicted
        else None,
        "comparison": "crow_model_vs_constant_calibration"
        if crow_only
        else "with_vs_without_auction",
        "paired_folds": comparisons,
        "equal_fold_mean_mae_delta_yuan_sqm": mean(
            f["model_minus_baseline_mae_yuan_sqm"] for f in comparisons
        )
        if comparisons
        else None,
        "interpretation": "Negative delta favors model; descriptive only. Overlapping six-month horizons and cities are dependent; no significance or nationwide generalization claimed. Coverage is only among constructed predictions, not all communities.",
    }
