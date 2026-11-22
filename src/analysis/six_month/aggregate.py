"""Read existing Crow archives into community-month observations, not forecasts."""

from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from .contracts import HOLDOUT_CITIES, TRAIN_CITIES, parse_date
from .inputs import archive_candidate
from .source_records import read_source_files


def aggregate_archives(root: Path, layout: str = "daily-archive") -> dict:
    groups, skipped, seen = defaultdict(list), Counter(), {}
    conflicts = set()
    for path, data, _ in read_source_files(root, layout):
        for raw in data:
            row = archive_candidate(raw, str(path.relative_to(root)))
            if row["city"] not in TRAIN_CITIES + HOLDOUT_CITIES:
                continue
            try:
                month = parse_date(row["traded_at"]).strftime("%Y-%m")
            except (ValueError, TypeError):
                skipped["invalid_transaction_date"] += 1
                continue
            if not row["sold"] or not row["community"] or not row["unit_price"]:
                skipped["missing_core_fields_or_unverified_sale"] += 1
                continue
            if row["raw_housing_type"] in (
                "商业",
                "商铺",
                "办公",
                "车位",
                "工业",
                "厂房",
                "土地",
            ):
                skipped["explicit_non_residential"] += 1
                continue
            # Reject inconsistent reported unit prices; never guess unit conversions.
            try:
                reported = float(raw.get("单价") or 0)
            except (TypeError, ValueError):
                reported = 0
            if reported > 0 and abs(row["unit_price"] / reported - 1) > 0.05:
                skipped["price_area_unit_inconsistent"] += 1
                continue
            key = (row["city"], row["district"] or "", row["community"], month)
            event = (key, row["unit_price"])
            rid = row["record_id"]
            if not rid:
                skipped["missing_item_id"] += 1
                continue
            if rid in seen and seen[rid] != event:
                conflicts.add(rid)
            seen[rid] = event
    for rid, (key, value) in seen.items():
        if rid not in conflicts:
            groups[key].append(value)
    skipped["conflicting_item_ids"] = len(conflicts)
    return {
        "status": "real_crow_aggregation_only_no_resale_accuracy_claim",
        "source_layout": layout,
        "location_resolution": "raw_community_or_locality_unverified",
        "availability": "historical_field_availability_unverified_not_backtest_ready",
        "deduplication": "auction_item_only_not_verified_physical_asset",
        "unknown_housing_type": "retained_not_certified_residential",
        "skipped": dict(skipped),
        "community_months": [
            {
                "city": key[0],
                "district": key[1],
                "community": key[2],
                "month": key[3],
                "auction_median_yuan_sqm": median(values),
                "n": len(values),
            }
            for key, values in sorted(groups.items())
        ],
    }
