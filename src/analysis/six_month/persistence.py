"""Portable ridge artifacts: JSON numbers only, never pickle/executable payloads."""

import json
from hashlib import sha256
from pathlib import Path

import numpy as np

from .contracts import SPLIT_VERSION, TRAIN_CITIES, parse_date
from .dataset import AUCTION_FEATURES, BASE_FEATURES
from .models import FittedModel

ARTIFACT_VERSION = "crow-six-month-ridge-v1"


def export_model(model: FittedModel, input_sha256: str) -> dict:
    if model.backend != "ridge":
        raise ValueError("portable artifact currently supports ridge only")
    payload = {
        "artifact_version": ARTIFACT_VERSION,
        "split_version": SPLIT_VERSION,
        "backend": model.backend,
        "input_mode": model.input_mode,
        "synthetic": model.synthetic,
        "training_cities": list(model.training_cities),
        "trained_rows": model.trained_rows,
        "cutoff": str(model.cutoff),
        "feature_names": list(model.feature_names),
        "center": model.center.tolist(),
        "scale": model.scale.tolist(),
        "coefficients": model.estimator.tolist(),
        "training_input_sha256": input_sha256,
        "label_definition": "resale_cell_median_month_t_plus_6_v1",
        "validation": "experimental_not_certified_accuracy",
    }
    decode_model(payload)
    return payload


def decode_model(payload: dict) -> FittedModel:
    if (
        payload.get("artifact_version") != ARTIFACT_VERSION
        or payload.get("split_version") != SPLIT_VERSION
    ):
        raise ValueError("unsupported artifact or city split version")
    if payload.get("backend") != "ridge" or payload.get("input_mode") not in (
        "crow_only",
        "market_augmented",
    ):
        raise ValueError("unsupported model backend or input contract")
    if payload.get("label_definition") != "resale_cell_median_month_t_plus_6_v1":
        raise ValueError("unsupported target contract")
    if not isinstance(payload.get("synthetic"), bool):
        raise TypeError("artifact must explicitly declare synthetic status")
    cities = tuple(payload.get("training_cities", []))
    if not cities or not set(cities).issubset(TRAIN_CITIES):
        raise ValueError("artifact declares training outside permitted cities")
    n = payload.get("trained_rows")
    if type(n) is not int or n <= 0:
        raise ValueError("invalid trained row count")
    names = tuple(payload.get("feature_names", []))
    if names not in (BASE_FEATURES, BASE_FEATURES + AUCTION_FEATURES):
        raise ValueError("feature contract/order does not match implementation")
    arrays = [
        np.asarray(payload.get(k), dtype=float)
        for k in ("center", "scale", "coefficients")
    ]
    if (
        any(
            a.shape != (len(names) + (i == 2),) or not np.isfinite(a).all()
            for i, a in enumerate(arrays)
        )
        or (arrays[1] <= 0).any()
    ):
        raise ValueError("invalid model dimensions, values, or scaling")
    return FittedModel(
        "ridge",
        names,
        arrays[0],
        arrays[1],
        arrays[2],
        parse_date(payload["cutoff"]),
        n,
        payload["input_mode"],
        payload["synthetic"],
        cities,
    )


def load_model(path: Path) -> tuple[FittedModel, str]:
    raw = path.read_bytes()
    return decode_model(json.loads(raw.decode("utf-8-sig"))), sha256(raw).hexdigest()
