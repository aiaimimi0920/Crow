"""Rolling training-city validation, then frozen holdout-city inference."""

from __future__ import annotations

from datetime import date

import numpy as np

from .contracts import HOLDOUT_CITIES, SPLIT_VERSION, TRAIN_CITIES
from .dataset import Example
from .models import fit
from .rolling_summary import summarize_folds
from .temporal import fold_manifest, validate_examples


def metrics(actual, predicted):
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    if not len(actual):
        return {"n": 0}
    error = np.abs(actual - predicted)
    return {
        "n": len(actual),
        "mae_yuan_sqm": float(error.mean()),
        "median_ape": float(np.median(error / actual)),
        "wape": float(error.sum() / actual.sum()),
    }


def backtest(
    examples: list[Example],
    cutoffs: list[date],
    *,
    backend: str = "ridge",
    holdout: bool = False,
    evaluation_asof: date,
) -> dict:
    validate_examples(examples)
    if len({r.synthetic for r in examples}) > 1:
        raise ValueError("cannot mix real and synthetic examples")
    if len({r.input_mode for r in examples}) > 1:
        raise ValueError("cannot mix feature modes")
    crow_only = not examples or examples[0].input_mode == "crow_only"
    base_name = "crow_constant_calibration" if crow_only else "without_auction"
    model_name = "crow_model" if crow_only else "with_auction"
    persistence_name = (
        "auction_price_unchanged_not_market_forecast" if crow_only else "no_change"
    )
    if holdout and len(cutoffs) != 1:
        raise ValueError("final holdout requires one frozen cutoff")
    folds = []
    for cutoff in sorted(set(cutoffs)):
        if evaluation_asof < cutoff:
            raise ValueError("evaluation as-of precedes fit cutoff")
        train = [
            r
            for r in examples
            if r.group[0] in TRAIN_CITIES
            and r.origin < cutoff
            and r.target is not None
            and r.label_available_at is not None
            and r.label_available_at <= cutoff
        ]
        allowed = HOLDOUT_CITIES if holdout else TRAIN_CITIES
        test = [r for r in examples if r.group[0] in allowed and r.origin == cutoff]
        if not train or not test:
            folds.append(
                {
                    "cutoff": str(cutoff),
                    "status": "insufficient_training_or_test_data",
                    "manifest": fold_manifest(train, test, cutoff),
                }
            )
            continue
        without = fit(train, cutoff, auction=False, backend=backend).predict(test)
        with_auction = fit(train, cutoff, auction=True, backend=backend).predict(test)
        scored = [
            i
            for i, r in enumerate(test)
            if r.target is not None and r.label_available_at <= evaluation_asof
        ]
        predictions = [
            {
                "group": list(r.group),
                "origin": str(r.origin),
                "target_month": r.target_month,
                "baseline": r.baseline,
                base_name: float(without[i]),
                model_name: float(with_auction[i]),
                "composition": r.composition,
                "actual": r.target if i in scored else None,
                "label_available_at": str(r.label_available_at)
                if i in scored
                else None,
                "target_count": r.target_count if i in scored else None,
            }
            for i, r in enumerate(test)
        ]
        actual = [test[i].target for i in scored]
        scores = {}
        for name, pred in (
            (persistence_name, [r.baseline for r in test]),
            (base_name, without),
            (model_name, with_auction),
        ):
            scores[name] = metrics(actual, [pred[i] for i in scored])
        city_scores = {
            city: {
                name: metrics(
                    [
                        p["actual"]
                        for p in predictions
                        if p["group"][0] == city and p["actual"] is not None
                    ],
                    [
                        p[key]
                        for p in predictions
                        if p["group"][0] == city and p["actual"] is not None
                    ],
                )
                for name, key in (
                    (persistence_name, "baseline"),
                    (base_name, base_name),
                    (model_name, model_name),
                )
            }
            for city in allowed
        }
        folds.append(
            {
                "cutoff": str(cutoff),
                "trained_rows": len(train),
                "manifest": fold_manifest(train, test, cutoff),
                "status": "scored" if scored else "predictions_only_labels_unavailable",
                "scores": scores,
                "city_scores": city_scores,
                "predictions": predictions,
            }
        )
    return {
        "split_version": SPLIT_VERSION,
        "backend": backend,
        "input_mode": "crow_only" if crow_only else "market_augmented",
        "auction_ablation_available": not crow_only,
        "mode": "final_holdout" if holdout else "training_city_temporal_validation",
        "evidence": "synthetic_pipeline_test_only"
        if examples and examples[0].synthetic
        else "real_data_experimental",
        "evaluation_asof": str(evaluation_asof),
        "folds": folds,
        "rolling_summary": summarize_folds(folds, base_name, model_name, crow_only),
        "limitations": [
            "Matched-cell medians are not hedonic quality-adjusted prices.",
            "No calibrated prediction intervals; not production ready.",
            "Ablation is predictive evidence, not a causal proof.",
        ],
    }
