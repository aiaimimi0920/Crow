"""Train-only preprocessing; direct six-month log-return models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from .contracts import TRAIN_CITIES
from .dataset import AUCTION_FEATURES, BASE_FEATURES, Example
from .temporal import validate_examples


@dataclass
class FittedModel:
    backend: str
    feature_names: tuple[str, ...]
    center: np.ndarray
    scale: np.ndarray
    estimator: object
    cutoff: date
    trained_rows: int
    input_mode: str
    synthetic: bool
    training_cities: tuple[str, ...]

    def predict(self, rows: list[Example]) -> np.ndarray:
        if any(r.synthetic != self.synthetic for r in rows):
            raise ValueError(
                "synthetic model/data cannot be mixed with real model/data"
            )
        if any(r.input_mode != self.input_mode for r in rows):
            raise ValueError("prediction input mode differs from trained model")
        if any(r.origin < self.cutoff for r in rows):
            raise ValueError("prediction precedes training cutoff")
        if not rows:
            return np.array([])
        x = _matrix(rows, self.feature_names)
        if self.backend == "ridge":
            x = np.column_stack([np.ones(len(x)), (x - self.center) / self.scale])
            change = x @ self.estimator
        else:
            change = self.estimator.predict(x)
        values = np.array([r.baseline for r in rows]) * np.exp(change)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError(
                "non-positive or non-finite prediction: model is not releaseable"
            )
        return values


def _matrix(rows, names):
    x = np.array([[r.features[name] for name in names] for r in rows], dtype=float)
    if not np.isfinite(x).all():
        raise ValueError("non-finite features")
    return x


def fit(
    rows: list[Example],
    cutoff: date,
    *,
    auction: bool = True,
    backend: str = "ridge",
    penalty: float = 10.0,
) -> FittedModel:
    validate_examples(rows)
    if not rows or any(r.group[0] not in TRAIN_CITIES for r in rows):
        raise ValueError("fit accepts training cities only, never holdout cities")
    if any(
        r.target is None
        or r.label_available_at is None
        or r.label_available_at > cutoff
        or r.origin >= cutoff
        for r in rows
    ):
        raise ValueError("all training labels must be mature and available by cutoff")
    if len({r.synthetic for r in rows}) != 1:
        raise ValueError("cannot mix synthetic and real examples")
    if len({r.input_mode for r in rows}) != 1:
        raise ValueError("cannot mix input modes")
    names = BASE_FEATURES + (AUCTION_FEATURES if auction else ())
    x = _matrix(rows, names)
    y = np.log([r.target / r.baseline for r in rows])
    center, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale == 0] = 1.0
    if backend == "ridge":
        if penalty <= 0:
            raise ValueError("ridge penalty must be positive")
        design = np.column_stack([np.ones(len(x)), (x - center) / scale])
        regularizer = np.diag([0.0] + [penalty] * len(names))
        estimator = np.linalg.solve(design.T @ design + regularizer, design.T @ y)
    elif backend == "lightgbm":
        from lightgbm import LGBMRegressor

        estimator = LGBMRegressor(
            n_estimators=150,
            num_leaves=7,
            min_child_samples=20,
            learning_rate=0.03,
            random_state=20261117,
            n_jobs=1,
            verbosity=-1,
        )
        estimator.fit(x, y)
    elif backend == "catboost":
        from catboost import CatBoostRegressor

        estimator = CatBoostRegressor(
            iterations=150,
            depth=4,
            learning_rate=0.03,
            random_seed=20261117,
            thread_count=1,
            verbose=False,
            allow_writing_files=False,
        )
        estimator.fit(x, y)
    else:
        raise ValueError(f"unknown backend: {backend}")
    return FittedModel(
        backend,
        names,
        center,
        scale,
        estimator,
        cutoff,
        len(rows),
        rows[0].input_mode,
        rows[0].synthetic,
        tuple(sorted({r.group[0] for r in rows})),
    )
