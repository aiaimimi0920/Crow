"""Read-only Wuhan public-label readiness, never opens the Shanghai holdout."""

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from statistics import median

from .contracts import add_months

WUHAN_PUBLICATION = date(2021, 4, 27)
WUHAN_SOURCE = "https://figshare.com/articles/dataset/city_house_info/14493858/1"


def read_wuhan_labels(path: Path) -> tuple[list[dict], dict]:
    from openpyxl import load_workbook
    from openpyxl.utils.datetime import from_excel

    book = load_workbook(path, read_only=True, data_only=True)
    result, rejected = [], Counter()
    try:
        rows = book.active.iter_rows(values_only=True)
        header = next(rows)
        if tuple(header[:10]) != (
            "城市",
            "小区名称",
            "室",
            "厅",
            "室厅",
            "面积",
            "装修情况",
            "成交日期",
            "总价",
            "成交价格",
        ):
            raise ValueError("Wuhan workbook schema changed; inspect before adapting")
        for number, row in enumerate(rows, 2):
            if row[0] != "武汉市" or not row[1]:
                rejected["missing_city_or_community"] += 1
                continue
            try:
                traded = (
                    from_excel(row[7], book.epoch)
                    if isinstance(row[7], (int, float))
                    else row[7]
                )
                if isinstance(traded, datetime):
                    traded = traded.date()
                if not isinstance(traded, date):
                    raise TypeError("invalid trade date")
                area, unit, total = float(row[5]), float(row[9]), float(row[8])
                if not all(isfinite(v) and v > 0 for v in (area, unit, total)):
                    raise ValueError("invalid price or area")
            except (ValueError, TypeError, OverflowError):
                rejected["invalid_date_or_positive_numeric_fields"] += 1
                continue
            result.append(
                {
                    "source_row": number,
                    "community": str(row[1]).strip(),
                    "month": traded.strftime("%Y-%m"),
                    "traded_at": traded,
                    "unit_price": unit,
                    "area": area,
                    "price_ratio_assuming_total_wan": total * 10000 / (area * unit),
                }
            )
    finally:
        book.close()
    return result, {
        "source": WUHAN_SOURCE,
        "license": "CC BY 4.0",
        "publication_date": str(WUHAN_PUBLICATION),
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "rejected": dict(rejected),
    }


def readiness_report(workbook: Path, crow_aggregation: Path) -> dict:
    labels, source = read_wuhan_labels(workbook)
    # Use only this training city. The aggregation contains no ordinary resale targets.
    payload = json.loads(crow_aggregation.read_text(encoding="utf-8-sig"))
    auctions = [row for row in payload["community_months"] if row["city"] == "武汉"]
    district_names = defaultdict(set)
    for row in auctions:
        district_names[row["community"].strip()].add(row["district"])
    label_groups = defaultdict(list)
    for row in labels:
        label_groups[(row["community"], row["month"])].append(row)
    label_names = {r["community"] for r in labels}
    common = label_names & set(district_names)
    ambiguous = {
        name
        for name in common
        if len(district_names[name]) != 1 or "" in district_names[name]
    }
    candidate = common - ambiguous
    joined = []
    for auction in auctions:
        name = auction["community"].strip()
        if name not in candidate:
            continue
        origin = date.fromisoformat(auction["month"] + "-01")
        target = add_months(origin, 6).strftime("%Y-%m")
        future = label_groups.get((name, target), [])
        if future:
            joined.append(
                {
                    "origin_month": auction["month"],
                    "target_month": target,
                    "auction_n": auction["n"],
                    "label_n": len(future),
                }
            )
    latest_label = max((r["traded_at"] for r in labels), default=None)
    latest_origin = (
        add_months(latest_label.replace(day=1), -6) if latest_label else None
    )
    return {
        "status": "training_city_readiness_only_no_model_fit_no_accuracy",
        "source": source,
        "label_rows": len(labels),
        "label_date_min": str(min(r["traded_at"] for r in labels)) if labels else None,
        "label_date_max": str(latest_label),
        "label_communities": len(label_names),
        "crow_wuhan_community_months": len(auctions),
        "crow_month_min": min((r["month"] for r in auctions), default=None),
        "crow_month_max": max((r["month"] for r in auctions), default=None),
        "exact_trimmed_name_candidates": len(common),
        "ambiguous_or_missing_crow_district_names": len(ambiguous),
        "single_crow_district_name_candidates": len(candidate),
        "six_month_pairs_before_verified_entity_linkage": len(joined),
        "pairs_with_at_least_3_target_rows": sum(r["label_n"] >= 3 for r in joined),
        "pair_origin_months": dict(Counter(r["origin_month"] for r in joined)),
        "median_ratio_total_wan_to_unit_times_area": median(
            r["price_ratio_assuming_total_wan"] for r in labels
        )
        if labels
        else None,
        "earliest_known_training_label_availability": str(WUHAN_PUBLICATION),
        "latest_possible_test_origin_month": latest_origin.strftime("%Y-%m")
        if latest_origin
        else None,
        "strict_historical_walkforward_possible_from_this_snapshot_alone": bool(
            latest_origin and latest_origin >= WUHAN_PUBLICATION
        ),
        "blockers": [
            "No source district or stable community ID: exact names are candidates, not verified links.",
            "Public snapshot first available 2021-04-27, after all observed target periods; cannot backdate label availability.",
            "Crow historical field availability and physical-property linkage remain unverified.",
            "Workbook has no original transaction URLs; broker transaction meaning is not verified official contract registration.",
        ],
        "holdout": "Shanghai workbook not opened; no heldout labels scored or used to select parameters",
    }
