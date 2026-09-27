from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from .adapters.auction_communities import (
    apply_community_resolution,
    load_default_community_index,
    resolve_community_name,
)
from .record_values import parse_area_sqm, parse_money_to_yuan, safe_float

_CONTRACT_RESOURCE = Path(__file__).with_name("collection_contract_v1.json")
_FROZEN_CONTRACT: Dict[str, Any] = json.loads(
    _CONTRACT_RESOURCE.read_text(encoding="utf-8")
)


def get_collection_template() -> Dict[str, Any]:
    """Return an isolated copy of the frozen collection contract."""

    return deepcopy(_FROZEN_CONTRACT)


_CONTRACT = get_collection_template()
_FINAL_TEMPLATE = _CONTRACT["final_template"]
_AUTHORITATIVE_FIELDS = _CONTRACT["authoritative_fields"]
_LEGACY_ALIASES = _CONTRACT["legacy_aliases"]

_MONEY_FIELDS = {
    "transaction_price",
    "starting_price",
    "actual_paid_price",
    "evaluation_price",
    "deposit",
}
_AREA_FIELDS = {"area_sqm", "gross_area_sqm", "interior_area_sqm", "land_area_sqm"}
_FLOAT_FIELDS = {
    "latitude",
    "longitude",
    "ownership_share_ratio",
    "extraction_confidence",
}
_FLOAT_FIELDS.add("community_name_confidence")
_INT_FIELDS = {
    "auction_round",
    "apply_count",
    "bid_count",
    "bidder_count",
    "watch_count",
    "reminder_count",
    "view_count",
    "build_year",
    "total_floors",
}
_BOOL_FIELDS = {
    "includes_parking",
    "special_school_tag",
    "has_keys",
    "has_elevator",
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "property_fee_owed",
    "is_restricted_purchase",
    "is_fractional_share",
    "tax_is_company_owned",
    "is_haunted",
    "has_lease_before_mortgage",
    "detail_captured",
    "is_processed",
}
_LIST_FIELDS = {"appraisal_report_urls", "announcement_attachment_urls"}
_STRING_FIELDS = {
    "item_id",
    "source_item_id",
    "source_url",
    "source_title",
    "source_platform",
    "detail_archive_path",
    "list_payload_path",
    "detail_text_path",
    "component_payload_path",
    "notice_text_path",
    "desc_text_path",
    "attachment_manifest_path",
    "image_manifest_path",
    "status",
    "auction_date",
    "auction_start_time",
    "full_address",
    "province",
    "city",
    "district",
    "business_area",
    "community_name",
    "coordinate_source",
    "housing_type",
    "layout",
    "floor_level",
    "orientation",
    "court_name",
    "case_number",
    "appraisal_agency_name",
    "appraisal_benchmark_date",
    "land_right_type",
    "tax_burden",
    "evidence_span",
    "evidence_source",
    "extraction_version",
    "community_name_source",
    "community_stable_key",
    "community_raw_name",
    "beike_community_id",
}


def get_empty_collection_record() -> Dict[str, Any]:
    return deepcopy(_FINAL_TEMPLATE)


def _normalized_non_empty(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    return value


def _get_risk_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    payload = item.get("avm_risk_features")
    return payload if isinstance(payload, dict) else {}


def _iter_candidate_values(item: Dict[str, Any], field: str) -> List[Any]:
    values: List[Any] = []
    risk_payload = _get_risk_payload(item)

    for section_name, section_fields in _AUTHORITATIVE_FIELDS.items():
        if field not in section_fields:
            continue
        section = item.get(section_name)
        if isinstance(section, dict):
            values.append(section.get(field))

    values.append(item.get(field))
    for alias in _LEGACY_ALIASES.get(field, []):
        values.append(item.get(alias))

    if field in risk_payload:
        values.append(risk_payload.get(field))

    return values


def _first_value(item: Dict[str, Any], field: str) -> Any:
    for value in _iter_candidate_values(item, field):
        normalized = _normalized_non_empty(value)
        if normalized is not None:
            return normalized
    return None


def _coerce_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "done", "成交"}:
        return True
    if text in {"false", "0", "no", "n", "pending", "unknown", "null"}:
        return False
    return None


def _coerce_int(value: Any) -> Optional[int]:
    number = safe_float(value)
    if number is None:
        return None
    try:
        return int(number)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> Optional[float]:
    number = safe_float(value)
    if number is None:
        return None
    return float(number)


def _coerce_ratio(value: Any, item: Dict[str, Any]) -> Optional[float]:
    number: float | None
    if value in (None, ""):
        fractional = _coerce_bool(_first_value(item, "is_fractional_share"))
        return None if fractional else 1.0
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        fraction_match = re.fullmatch(r"(\d+)\s*/\s*(\d+)", text)
        if fraction_match:
            numerator = float(fraction_match.group(1))
            denominator = float(fraction_match.group(2))
            if denominator == 0:
                return None
            number = numerator / denominator
        elif text.endswith("%"):
            number = (safe_float(text[:-1]) or 0.0) / 100.0
        else:
            number = safe_float(text)
            if number is None:
                return None
    if number > 1.0 and number <= 100.0:
        number = number / 100.0
    if number <= 0:
        return None
    return round(min(number, 1.0), 6)


def _coerce_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    parts = re.split(r"[\r\n,;]+", text)
    return [part.strip() for part in parts if part.strip()]


def _coerce_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_collection_record(
    item: Dict[str, Any], *, default_source_platform: str = "taobao_sf"
) -> Dict[str, Any]:
    record = get_empty_collection_record()
    record["source"]["source_platform"] = default_source_platform

    for section_name, fields in _AUTHORITATIVE_FIELDS.items():
        for field in fields:
            raw_value = _first_value(item, field)
            value: object
            if field in _MONEY_FIELDS:
                value = parse_money_to_yuan(raw_value)
            elif field in _AREA_FIELDS:
                value = parse_area_sqm(raw_value)
            elif field == "ownership_share_ratio":
                value = _coerce_ratio(raw_value, item)
            elif field in _FLOAT_FIELDS:
                value = _coerce_float(raw_value)
            elif field in _INT_FIELDS:
                value = _coerce_int(raw_value)
            elif field in _BOOL_FIELDS:
                value = _coerce_bool(raw_value)
            elif field in _LIST_FIELDS:
                value = _coerce_list(raw_value)
            else:
                value = _coerce_string(raw_value)
            if value not in (None, "", []):
                record[section_name][field] = value

    risk_flags = record["risk_flags"]
    property_section = record["property"]

    ratio = property_section.get("ownership_share_ratio")
    gross_area = property_section.get("gross_area_sqm")
    area = property_section.get("area_sqm")
    if gross_area is None and area is not None and ratio not in (None, 0):
        if ratio and ratio < 1:
            property_section["gross_area_sqm"] = round(area / ratio, 2)
        else:
            property_section["gross_area_sqm"] = area
            gross_area = area
    if area is None and gross_area is not None and ratio not in (None, 0):
        property_section["area_sqm"] = round(gross_area * ratio, 2)
    if (
        property_section.get("ownership_share_ratio") is None
        and risk_flags.get("is_fractional_share") is not True
    ):
        property_section["ownership_share_ratio"] = 1.0

    if not record["source"].get("source_item_id") and record["source"].get("item_id"):
        record["source"]["source_item_id"] = record["source"]["item_id"]
    if not record["source"].get("source_platform"):
        record["source"]["source_platform"] = default_source_platform

    return record


def sync_collection_record(item: Dict[str, Any]) -> Dict[str, Any]:
    record = build_collection_record(item)
    item.update(record)
    resolution = resolve_community_name(item, load_default_community_index())
    if resolution:
        apply_community_resolution(item, resolution)
        record = build_collection_record(item)
        item.update(record)
    if record["source"].get("source_item_id"):
        item.setdefault("source_item_id", record["source"]["source_item_id"])
    if record["source"].get("source_url"):
        item.setdefault("source_url", record["source"]["source_url"])
    if record["source"].get("source_title"):
        item.setdefault("source_title", record["source"]["source_title"])
    if record["location"].get("full_address"):
        item.setdefault("full_address", record["location"]["full_address"])
        item.setdefault("完整地址", record["location"]["full_address"])
        item.setdefault("地点", record["location"]["full_address"])
    if record["location"].get("city"):
        item.setdefault("城市", record["location"]["city"])
    if record["location"].get("district"):
        item.setdefault("区", record["location"]["district"])
    if record["location"].get("business_area"):
        item.setdefault("最靠近商圈", record["location"]["business_area"])
    if record["location"].get("community_name"):
        item.setdefault("所属小区", record["location"]["community_name"])
    if record["auction"].get("transaction_price") is not None:
        item.setdefault("成交价格", record["auction"]["transaction_price"])
        item.setdefault("transaction_price", record["auction"]["transaction_price"])
    if record["auction"].get("starting_price") is not None:
        item.setdefault("起拍价格", record["auction"]["starting_price"])
        item.setdefault("starting_price", record["auction"]["starting_price"])
    if record["auction"].get("evaluation_price") is not None:
        item.setdefault("市场评估价", record["auction"]["evaluation_price"])
    if record["auction"].get("deposit") is not None:
        item.setdefault("保证金", record["auction"]["deposit"])
        item.setdefault("deposit", record["auction"]["deposit"])
    if record["auction"].get("auction_date"):
        item.setdefault("交易时间", record["auction"]["auction_date"])
        item.setdefault("auction_date", record["auction"]["auction_date"])
    if record["auction"].get("bid_count") is not None:
        item.setdefault("出价次数", record["auction"]["bid_count"])
        item.setdefault("bid_count", record["auction"]["bid_count"])
    if record["auction"].get("bidder_count") is not None:
        item.setdefault("出价人数", record["auction"]["bidder_count"])
        item.setdefault("bidder_count", record["auction"]["bidder_count"])
    if record["auction"].get("apply_count") is not None:
        item.setdefault("竞拍人数", record["auction"]["apply_count"])
        item.setdefault("apply_count", record["auction"]["apply_count"])
    if record["property"].get("area_sqm") is not None:
        item.setdefault("建筑面积", record["property"]["area_sqm"])
    return item
