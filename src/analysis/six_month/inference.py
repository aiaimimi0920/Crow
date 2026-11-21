"""Separate training from later Crow-only inference with no resale input."""

from datetime import date
from pathlib import Path

from .contracts import TRAIN_CITIES
from .dataset import build_examples
from .inputs import load_transactions
from .models import fit
from .persistence import export_model, load_model


def train_artifact(input_path: Path, origins: list[date], cutoff: date) -> dict:
    rows, digest = load_transactions(input_path)
    # Holdout observations do not enter any feature-building or fitting step here.
    training_rows = [row for row in rows if row.city in TRAIN_CITIES]
    examples = build_examples(training_rows, origins, input_mode="crow_only")
    mature = [
        r
        for r in examples
        if r.origin < cutoff and r.target is not None and r.label_available_at <= cutoff
    ]
    if not mature:
        raise ValueError(
            "no mature ordinary resale labels; real market model cannot be trained yet"
        )
    return export_model(fit(mature, cutoff), digest)


def predict_report(model_path: Path, input_path: Path, origin: date) -> dict:
    model, model_hash = load_model(model_path)
    if model.input_mode != "crow_only":
        raise ValueError("standalone prediction accepts Crow-only models")
    rows, digest = load_transactions(input_path)
    if any(row.kind != "auction" for row in rows):
        raise ValueError(
            "prediction input must contain auctions only, no ordinary resale labels"
        )
    if any(row.synthetic != model.synthetic for row in rows):
        raise ValueError(
            "synthetic artifact cannot be applied to real Crow data or conversely"
        )
    if origin < model.cutoff:
        raise ValueError("prediction origin precedes model training cutoff")
    examples = build_examples(rows, [origin], input_mode="crow_only")
    predictions = model.predict(examples)
    return {
        "status": "predictions_generated"
        if examples
        else "insufficient_current_crow_history",
        "evidence": "synthetic_pipeline_test_only"
        if model.synthetic
        else "real_model_accuracy_not_certified",
        "model_sha256": model_hash,
        "input_sha256": digest,
        "origin": str(origin),
        "trained_at_cutoff": str(model.cutoff),
        "input_mode": "crow_only",
        "ordinary_resale_input_required": False,
        "label_definition": "resale_cell_median_month_t_plus_6_v1",
        "predictions": [
            {
                "group": list(row.group),
                "target_month": row.target_month,
                "predicted_resale_yuan_sqm": float(value),
                "interval": None,
                "interval_status": "not_calibrated",
                "composition": row.composition,
                "evidence_ids": list(row.evidence_ids),
            }
            for row, value in zip(examples, predictions)
        ],
        "limitations": [
            "Not quality-adjusted; no calibrated interval.",
            "A predicted number is not evidence of validated real accuracy.",
        ],
    }
