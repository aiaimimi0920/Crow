"""Read-only import: archive candidates are NOT verified training observations."""

from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from math import isfinite
from pathlib import Path

from .contracts import (
    HOLDOUT_CITIES,
    TRAIN_CITIES,
    Transaction,
    city_name,
    unique_transactions,
)
from .source_records import analysis_item_identity


def load_transactions(path: Path) -> tuple[list[Transaction], str]:
    content = path.read_bytes()
    payload = json.loads(content.decode("utf-8-sig"))
    if not isinstance(payload, list):
        raise TypeError("curated input must be a JSON array")
    rows = [Transaction.from_dict(row) for row in payload]
    return unique_transactions(rows), sha256(content).hexdigest()


def archive_candidate(row: dict, source: str) -> dict:
    auction = row.get("auction") if isinstance(row.get("auction"), dict) else {}
    location = row.get("location") if isinstance(row.get("location"), dict) else {}
    prop = row.get("property") if isinstance(row.get("property"), dict) else {}
    price = row.get("成交价格") or auction.get("transaction_price")
    area = row.get("建筑面积") or prop.get("gross_area_sqm") or prop.get("area_sqm")
    try:
        unit = (
            float(price) / float(area) if float(price) > 0 and float(area) > 0 else None
        )
        if unit is not None and (not isfinite(unit) or unit <= 0):
            unit = None
    except (TypeError, ValueError, ZeroDivisionError):
        unit = None
    return {
        "record_id": analysis_item_identity(row),
        "property_id": None,
        "kind": "auction",
        "city": city_name(row.get("城市") or location.get("city") or ""),
        "district": row.get("区") or location.get("district"),
        "community": row.get("所属小区") or location.get("community_name"),
        "house_type": row.get("户型") or prop.get("layout"),
        "traded_at": row.get("交易时间") or auction.get("auction_date"),
        "available_at": None,
        "unit_price": unit,
        "source": source,
        "sold": row.get("是否成交") is True,
        "residential": None,
        "full_ownership": None,
        "review_status": "requires_evidence_not_training_ready",
        "raw_housing_type": row.get("房屋用途") or prop.get("housing_type"),
        "raw_ownership_share": prop.get("ownership_share_ratio"),
        "raw_auction_status": auction.get("status"),
        "risk_flags": row.get("risk_flags") or {},
    }


def audit_archives(root: Path) -> dict:
    counts, missing, hashes = Counter(), Counter(), []
    ids = set()
    for path in sorted(root.rglob("*.json")):
        raw = path.read_bytes()
        hashes.append((str(path.relative_to(root)), sha256(raw).hexdigest()))
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, list):
            raise TypeError(f"unsupported archive container: {path.name}")
        for row in data:
            candidate = archive_candidate(row, str(path.relative_to(root)))
            if candidate["city"] not in TRAIN_CITIES + HOLDOUT_CITIES:
                continue
            counts[candidate["city"]] += 1
            ids.add(candidate["record_id"])
            for key in (
                "property_id",
                "house_type",
                "available_at",
                "unit_price",
                "community",
                "residential",
                "full_ownership",
            ):
                if candidate[key] in (None, ""):
                    missing[key] += 1
    return {
        "status": "raw_archive_audit_not_training",
        "files": len(hashes),
        "city_rows": dict(counts),
        "unique_item_ids": len(ids),
        "missing_or_unverified": dict(missing),
        "input_files_sha256": hashes,
    }
