"""Validate direct examples and expose reproducible, label-free fold membership."""

import json
from hashlib import sha256
from math import isfinite

from .contracts import add_months


def validate_examples(rows):
    seen = set()
    for row in rows:
        identity = (row.group, row.origin)
        if identity in seen:
            raise ValueError("duplicate group/origin example")
        seen.add(identity)
        month = add_months(row.origin, 6).replace(day=1)
        if row.target_month != month.strftime("%Y-%m"):
            raise ValueError("target month must be six calendar months after origin")
        if not isfinite(row.baseline) or row.baseline <= 0:
            raise ValueError("baseline must be finite and positive")
        if row.target is not None:
            if not isfinite(row.target) or row.target <= 0:
                raise ValueError("target must be finite and positive")
            if row.label_available_at is None or row.label_available_at < add_months(
                month, 1
            ):
                raise ValueError("label cannot mature before full target month closes")


def fold_manifest(train, test, cutoff):
    def membership(rows):
        return sorted([[*r.group, str(r.origin), r.target_month] for r in rows])

    encoded = json.dumps(
        {"train": membership(train), "test": membership(test)},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return {
        "protocol": "six-calendar-month-full-month-maturity-v1",
        "fit_cutoff": str(cutoff),
        "training_cities": sorted({r.group[0] for r in train}),
        "latest_training_origin": str(max(r.origin for r in train)) if train else None,
        "latest_training_label_available_at": str(
            max(r.label_available_at for r in train)
        )
        if train
        else None,
        "training_rows": len(train),
        "test_rows": len(test),
        "membership_sha256": sha256(encoded).hexdigest(),
        "membership_hash_scope": "group/origin/target_month only; not data or model hash",
    }
