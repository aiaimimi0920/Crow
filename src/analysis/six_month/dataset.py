"""Community-level typical prices with optional, never mandatory resale inputs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from math import log
from statistics import median

from .contracts import Transaction, add_months, unique_transactions

BASE_FEATURES = ("market_trend", "market_count", "market_area", "market_area_missing")
AUCTION_FEATURES = (
    "auction_discount",
    "auction_trend",
    "auction_count",
    "auction_missing",
    "auction_area",
    "auction_area_missing",
    "auction_use_unknown",
)


@dataclass(frozen=True)
class Example:
    group: tuple[str, str, str]
    origin: date
    target_month: str
    baseline: float
    features: dict[str, float]
    target: float | None
    label_available_at: date | None
    synthetic: bool
    evidence_ids: tuple[str, ...]
    target_count: int
    input_mode: str
    composition: dict


def build_examples(
    rows: list[Transaction],
    origins: list[date],
    min_count: int = 3,
    input_mode: str = "crow_only",
) -> list[Example]:
    if input_mode not in ("crow_only", "market_augmented"):
        raise ValueError("unknown input mode")
    if min_count < 2:
        raise ValueError("at least two transactions required per price aggregate")
    if len({r.synthetic for r in rows}) > 1:
        raise ValueError("cannot mix synthetic and real observations")
    groups: dict[tuple, list[Transaction]] = defaultdict(list)
    for row in unique_transactions(rows):
        groups[row.group].append(row)
    result = []
    for group, records in sorted(groups.items()):
        for origin in sorted(set(origins)):
            example = _one_example(group, records, origin, min_count, input_mode)
            if example:
                result.append(example)
    return result


def _one_example(group, records, origin, min_count, input_mode):
    history = [r for r in records if r.available_at <= origin and r.traded_at <= origin]
    input_kind = "auction" if input_mode == "crow_only" else "resale"
    current = [
        r
        for r in history
        if r.kind == input_kind and add_months(origin, -3) < r.traded_at
    ]
    previous = [
        r
        for r in history
        if r.kind == input_kind
        and add_months(origin, -6) < r.traded_at <= add_months(origin, -3)
    ]
    if len(current) < min_count or len(previous) < min_count:
        return None
    baseline = median(r.unit_price for r in current)
    auctions = [
        r
        for r in history
        if r.kind == "auction" and add_months(origin, -6) < r.traded_at
    ]
    a_recent = [r.unit_price for r in auctions if r.traded_at > add_months(origin, -3)]
    a_old = [r.unit_price for r in auctions if r.traded_at <= add_months(origin, -3)]
    enough = len(auctions) >= min_count
    areas = [r.area_sqm for r in current if r.area_sqm is not None]
    auction_areas = [r.area_sqm for r in auctions if r.area_sqm is not None]
    augmented = input_mode == "market_augmented"
    features = {
        "market_trend": log(baseline / median(r.unit_price for r in previous))
        if augmented
        else 0.0,
        "market_count": log(1 + len(current)) if augmented else 0.0,
        "market_area": log(median(areas)) if augmented and areas else 0.0,
        "market_area_missing": float(not areas) if augmented else 0.0,
        "auction_discount": log(median(r.unit_price for r in auctions) / baseline)
        if enough
        else 0.0,
        "auction_trend": log(median(a_recent) / median(a_old))
        if len(a_recent) >= min_count and len(a_old) >= min_count
        else 0.0,
        "auction_count": log(1 + len(auctions)),
        "auction_missing": float(not enough),
        "auction_area": log(median(auction_areas)) if auction_areas else 0.0,
        "auction_area_missing": float(not auction_areas),
        "auction_use_unknown": sum(r.residential is None for r in auctions)
        / len(auctions)
        if auctions
        else 1.0,
    }
    target_month = add_months(origin, 6).strftime("%Y-%m")
    labels = [
        r
        for r in records
        if r.kind == "resale" and r.traded_at.strftime("%Y-%m") == target_month
    ]
    target = median(r.unit_price for r in labels) if len(labels) >= min_count else None
    # Full target month must close, even if three sales were published early.
    end = add_months(add_months(origin, 6).replace(day=1), 1)
    available = max([end] + [r.available_at for r in labels]) if target else None
    evidence = current + previous + auctions
    return Example(
        group,
        origin,
        target_month,
        baseline,
        features,
        target,
        available,
        records[0].synthetic,
        tuple(f"{r.kind}:{r.record_id}" for r in evidence),
        len(labels),
        input_mode,
        {
            "input_use_unknown_share": sum(r.residential is None for r in current)
            / len(current),
            "input_layout_known_share": sum(bool(r.house_type) for r in current)
            / len(current),
            "input_ownership_unknown_share": sum(
                r.full_ownership is None for r in current
            )
            / len(current),
            "input_area_known_share": len(areas) / len(current),
            "input_count": len(current),
        },
    )
