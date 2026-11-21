"""Current snapshot feature preview, never a historical backtest or market quote."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import isfinite
from pathlib import Path

from .contracts import HOLDOUT_CITIES, TRAIN_CITIES, Transaction, parse_date
from .dataset import build_examples
from .inputs import archive_candidate
from .source_records import read_source_files

CHINA_TIME = timezone(timedelta(hours=8))


def current_snapshot_report(root: Path, layout: str = "daily-archive") -> dict:
    """No caller-supplied historical origin: bytes are only observed now."""
    observed_at = datetime.now(CHINA_TIME)
    origin = observed_at.date()
    if not root.is_dir():
        raise ValueError("archive directory does not exist")
    rows, conflicts, rejected, fingerprint = {}, set(), Counter(), sha256()
    for path, data, content_hash in read_source_files(root, layout):
        relative = str(path.relative_to(root))
        fingerprint.update(relative.encode("utf8") + b"\0" + content_hash)
        for raw in data:
            candidate = archive_candidate(raw, relative)
            if candidate["city"] not in TRAIN_CITIES + HOLDOUT_CITIES:
                continue
            try:
                row = _snapshot_row(candidate, raw, origin)
            except (ValueError, TypeError):
                rejected["unusable_core_fields_or_excluded_asset"] += 1
                continue
            if row.record_id in rows and rows[row.record_id] != row:
                conflicts.add(row.record_id)
            rows[row.record_id] = row
    usable = [row for rid, row in rows.items() if rid not in conflicts]
    examples = build_examples(usable, [origin], input_mode="crow_only")
    return {
        "status": "current_feature_preview_only"
        if examples
        else "refused_no_recent_crow_history",
        "observed_at": observed_at.isoformat(),
        "origin": str(origin),
        "source_snapshot_sha256": fingerprint.hexdigest(),
        "source_layout": layout,
        "location_resolution": "raw_community_or_locality_unverified_not_exact_community_identity",
        "latest_usable_auction_date": str(
            max((r.traded_at for r in usable), default=None)
        ),
        "market_predictions": [],
        "market_prediction_status": "not_attempted_no_real_calibrated_model",
        "identity_policy": "auction_item_only_physical_property_unresolved",
        "availability_policy": "observed_now_only_not_evidence_of_historical_availability",
        "rejected": dict(rejected),
        "conflicting_item_ids": len(conflicts),
        "feature_candidates": [
            {
                "group": list(row.group),
                "target_month": row.target_month,
                "features": row.features,
                "auction_reference_yuan_sqm": row.baseline,
                "composition": row.composition,
            }
            for row in examples
        ],
        "limitations": [
            "Raw auction IDs are not verified physical-property identities; repeats may remain.",
            "Community names are not verified external-label linkage IDs.",
            "This preview is not a training dataset or six-month ordinary-market price prediction.",
            "Latest loaded snapshot may not be transactionally consistent while collector is writing.",
        ],
    }


def _snapshot_row(candidate: dict, raw: dict, origin) -> Transaction:
    if not candidate["sold"] or any(
        not candidate[k] for k in ("record_id", "district", "community", "unit_price")
    ):
        raise ValueError("missing transaction core")
    if candidate["raw_housing_type"] in (
        "商业",
        "商铺",
        "办公",
        "车位",
        "工业",
        "厂房",
        "土地",
    ):
        raise ValueError("explicit non-residential")
    traded = parse_date(candidate["traded_at"])
    if traded > origin:
        raise ValueError("future trade")
    reported = float(raw.get("单价") or 0)
    if reported and (
        not isfinite(reported)
        or reported <= 0
        or abs(candidate["unit_price"] / reported - 1) > 0.05
    ):
        raise ValueError("inconsistent reported price")
    share = candidate["raw_ownership_share"]
    if share is not None and float(share) < 1:
        raise ValueError("explicit fractional share")
    prop = raw.get("property") if isinstance(raw.get("property"), dict) else {}
    area = raw.get("建筑面积") or prop.get("gross_area_sqm") or prop.get("area_sqm")
    area = float(area)
    if not isfinite(area) or area <= 0:
        raise ValueError("invalid area")
    return Transaction(
        candidate["record_id"],
        "UNRESOLVED_ASSET_FOR_ITEM:" + candidate["record_id"],
        "auction",
        candidate["city"],
        candidate["district"],
        candidate["community"],
        str(candidate["house_type"] or ""),
        traded,
        origin,
        candidate["unit_price"],
        "current_archive_snapshot",
        False,
        None,
        None,
        area,
    )
