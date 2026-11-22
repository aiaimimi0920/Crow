"""Versioned, point-in-time data contracts and frozen geographic split."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import isfinite

TRAIN_CITIES = ("北京", "武汉", "温州", "宜昌")
HOLDOUT_CITIES = ("上海", "佛山", "金华", "淮安")
SPLIT_VERSION = "yicai2025-seed20261117-v1"


def parse_date(value: str) -> date:
    # Collector naive timestamps are Beijing local time, never host-local time.
    # Explicit offsets must be converted before selecting the calendar date.
    text = str(value).strip().replace("/", "-")
    if len(text) == 10:
        return date.fromisoformat(text)
    stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(timezone(timedelta(hours=8)))
    return stamp.date()


def add_months(value: date, months: int) -> date:
    n = value.year * 12 + value.month - 1 + months
    year, month = divmod(n, 12)
    return date(year, month + 1, min(value.day, monthrange(year, month + 1)[1]))


def city_name(value: str) -> str:
    return str(value).strip().removesuffix("市")


@dataclass(frozen=True)
class Transaction:
    record_id: str
    property_id: str
    kind: str
    city: str
    district: str
    community: str
    house_type: str
    traded_at: date
    available_at: date
    unit_price: float
    source: str
    synthetic: bool = False
    residential: bool | None = None
    full_ownership: bool | None = None
    area_sqm: float | None = None

    @property
    def group(self) -> tuple[str, str, str]:
        return self.city, self.district, self.community

    @classmethod
    def from_dict(cls, row: dict) -> Transaction:
        for key in ("residential", "full_ownership"):
            if row.get(key) is not None and not isinstance(row[key], bool):
                raise TypeError(f"{key} must be boolean or unknown")
        if row.get("residential") is False or row.get("full_ownership") is False:
            raise ValueError(
                "explicit non-residential or fractional ownership excluded"
            )
        if row.get("sold") is not True:
            raise ValueError("requires successful transaction, not a listing/appraisal")
        required = (
            "record_id",
            "property_id",
            "kind",
            "city",
            "district",
            "community",
            "traded_at",
            "available_at",
            "unit_price",
            "source",
        )
        if any(row.get(k) in (None, "") for k in required):
            raise ValueError("missing required provenance, match key, time or price")
        if row["kind"] not in ("auction", "resale"):
            raise ValueError("kind must distinguish auction from actual resale")
        if not isinstance(row.get("synthetic", False), bool):
            raise TypeError("synthetic must be boolean")
        traded, available = (
            parse_date(row["traded_at"]),
            parse_date(row["available_at"]),
        )
        price = float(row["unit_price"])
        if not isfinite(price) or price <= 0 or available < traded:
            raise ValueError("invalid price or availability before transaction")
        city = city_name(row["city"])
        area = row.get("area_sqm")
        if area is not None and (not isfinite(float(area)) or float(area) <= 0):
            raise ValueError("invalid area")
        if city not in TRAIN_CITIES + HOLDOUT_CITIES:
            raise ValueError("city outside frozen experiment")
        return cls(
            str(row["record_id"]),
            str(row["property_id"]),
            row["kind"],
            city,
            str(row["district"]),
            str(row["community"]),
            str(row.get("house_type") or ""),
            traded,
            available,
            price,
            str(row["source"]),
            row.get("synthetic", False),
            row.get("residential"),
            row.get("full_ownership"),
            float(area) if area is not None else None,
        )


def unique_transactions(rows: list[Transaction]) -> list[Transaction]:
    """Reject conflicting versions; never silently select a future revision."""
    if len({row.synthetic for row in rows}) > 1:
        raise ValueError("cannot mix synthetic and real transactions")
    by_id: dict[tuple[str, str], Transaction] = {}
    by_event: dict[tuple, Transaction] = {}
    for row in rows:
        key = row.kind, row.record_id
        event = row.kind, row.property_id, row.traded_at
        if key in by_id and by_id[key] != row:
            raise ValueError(f"conflicting record versions: {key}")
        by_id[key] = row
        if event in by_event:
            old = by_event[event]
            if any(
                getattr(old, name) != getattr(row, name)
                for name in (
                    "unit_price",
                    "group",
                    "synthetic",
                    "residential",
                    "area_sqm",
                    "full_ownership",
                    "house_type",
                )
            ):
                raise ValueError(f"conflicting property transaction: {event}")
            if old.available_at <= row.available_at:
                continue
        by_event[event] = row
    return sorted(by_event.values(), key=lambda r: (r.traded_at, r.kind, r.record_id))
