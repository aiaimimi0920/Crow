from __future__ import annotations
from tools.live_smoke_context import *  # noqa: F401,F403
from tools.live_smoke_resume import *  # noqa: F401,F403
from tools.live_smoke_list import *  # noqa: F401,F403
from tools.live_smoke_area import *  # noqa: F401,F403
from tools.live_smoke_auth import *  # noqa: F401,F403
from tools.live_smoke_cdp import *  # noqa: F401,F403
from tools.live_smoke_browser import *  # noqa: F401,F403


def risk_aliases(item: dict[str, Any]) -> None:
    risk_payload = item.get("avm_risk_features")
    if not isinstance(risk_payload, dict):
        return
    for key, value in risk_payload.items():
        if has_value(value):
            item.setdefault(key, value)
    if risk_payload.get("community_name") and not item.get("所属小区"):
        item["所属小区"] = risk_payload["community_name"]

def build_description_audit(html: str, item_dir: Path) -> dict[str, Any]:
    from src import llm_helper
    from tools.description_capture import fetch_description_with_deadline

    audit: dict[str, Any] = {
        "area_sqm": None,
        "text_len": 0,
        "has_area_marker": False,
        "text_path": None,
    }
    desc_text = fetch_description_with_deadline(html)
    if not desc_text:
        return audit
    desc_path = item_dir / "description-data.txt"
    desc_path.write_text(desc_text, encoding="utf-8")
    area = llm_helper.extract_area_from_text(desc_text)
    audit["area_sqm"] = area
    audit["text_len"] = len(desc_text)
    audit["has_area_marker"] = area is not None
    audit["text_path"] = str(desc_path)
    return audit

def selected_summary(
    *,
    seed: dict[str, Any],
    html: str,
    final_url: str,
    detail_bytes: int,
    fetch_method: str,
    extracted: dict[str, Any],
    final_item: dict[str, Any],
    description_data: dict[str, Any],
) -> dict[str, Any]:
    location = as_dict(final_item.get("location"))
    source = as_dict(final_item.get("source"))
    auction = as_dict(final_item.get("auction"))
    prop = as_dict(final_item.get("property"))
    risk_features = as_dict(final_item.get("avm_risk_features"))
    return {
        "item_id": str(seed.get("id")),
        "fetch": {
            "method": fetch_method,
            "detail_final_url": final_url,
            "detail_html_bytes": detail_bytes,
            "html_has_description_data": "description-data" in html,
            "html_has_challenge": is_challenge_page(html, final_url),
        },
        "trusted_seed": {
            "title": seed.get("title"),
            "currentPrice": seed.get("currentPrice"),
            "initialPrice": seed.get("initialPrice"),
            "auction_date": seed.get("auction_date"),
            "status": seed.get("status"),
            "bidCount": seed.get("bidCount"),
            "applyCount": seed.get("applyCount"),
        },
        "final_core": {
            "id": final_item.get("id"),
            "source_item_id": pick_first(final_item.get("source_item_id"), source.get("source_item_id")),
            "source_url": pick_first(final_item.get("source_url"), source.get("source_url"), final_item.get("原始网站")),
            "title": pick_first(final_item.get("title"), final_item.get("标题"), source.get("source_title")),
            "is_processed": final_item.get("is_processed"),
            "detail_captured": final_item.get("detail_captured"),
        },
        "location_and_stable_index": {
            "full_address": pick_first(final_item.get("完整地址"), final_item.get("full_address"), location.get("full_address"), final_item.get("地点")),
            "city": pick_first(final_item.get("城市"), final_item.get("city"), location.get("city")),
            "district": pick_first(final_item.get("区"), final_item.get("district"), location.get("district")),
            "business_area": pick_first(final_item.get("最靠近商圈"), final_item.get("business_area"), location.get("business_area")),
            "community_name": pick_first(location.get("community_name"), final_item.get("所属小区"), final_item.get("community_name")),
            "community_name_source": pick_first(location.get("community_name_source"), final_item.get("community_name_source")),
            "community_name_confidence": pick_first(location.get("community_name_confidence"), final_item.get("community_name_confidence")),
            "community_stable_key": pick_first(location.get("community_stable_key"), final_item.get("community_stable_key")),
        },
        "auction_and_property": {
            "transaction_price": pick_first(final_item.get("成交价格"), final_item.get("transaction_price"), auction.get("transaction_price")),
            "starting_price": pick_first(final_item.get("起拍价格"), final_item.get("starting_price"), auction.get("starting_price")),
            "evaluation_price": pick_first(final_item.get("市场评估价"), auction.get("evaluation_price")),
            "deposit": pick_first(final_item.get("保证金"), final_item.get("deposit"), auction.get("deposit")),
            "auction_date": pick_first(final_item.get("交易时间"), final_item.get("auction_date"), auction.get("auction_date")),
            "bid_count": pick_first(final_item.get("出价次数"), final_item.get("bid_count"), auction.get("bid_count")),
            "apply_count": pick_first(final_item.get("竞拍人数"), final_item.get("apply_count"), auction.get("apply_count")),
            "area_sqm": pick_first(final_item.get("建筑面积"), final_item.get("area_sqm"), prop.get("area_sqm")),
            "gross_area_sqm": prop.get("gross_area_sqm"),
            "ownership_share_ratio": pick_first(final_item.get("产权份额比例"), prop.get("ownership_share_ratio")),
            "unit_price": pick_first(final_item.get("单价"), prop.get("unit_price")),
        },
        "description_data": description_data,
        "ai_extracted_raw_core": {
            "id": extracted.get("id"),
            "标题": extracted.get("标题"),
            "完整地址": extracted.get("完整地址"),
            "所属小区": extracted.get("所属小区"),
            "城市": extracted.get("城市"),
            "区": extracted.get("区"),
            "最靠近商圈": extracted.get("最靠近商圈"),
            "建筑面积": extracted.get("建筑面积"),
            "成交价格": extracted.get("成交价格"),
            "单价": extracted.get("单价"),
        },
        "risk_sample": {
            "community_name": risk_features.get("community_name"),
            "housing_type": risk_features.get("housing_type"),
            "floor_level": risk_features.get("floor_level"),
            "evidence_source": risk_features.get("evidence_source"),
            "extraction_confidence": risk_features.get("extraction_confidence"),
        },
    }

def raw_detail_summary(
    *,
    seed: dict[str, Any],
    html: str,
    final_url: str,
    detail_bytes: int,
    fetch_method: str,
    description_data: dict[str, Any],
    item_dir: Path,
) -> dict[str, Any]:
    return {
        "item_id": str(seed.get("id")),
        "detail_capture_mode": "raw",
        "fetch": {
            "method": fetch_method,
            "detail_final_url": final_url,
            "detail_html_bytes": detail_bytes,
            "html_has_description_data": "description-data" in html,
            "html_has_challenge": is_challenge_page(html, final_url),
        },
        "trusted_seed": {
            "title": seed.get("title"),
            "currentPrice": seed.get("currentPrice"),
            "initialPrice": seed.get("initialPrice"),
            "auction_date": seed.get("auction_date"),
            "status": seed.get("status"),
            "bidCount": seed.get("bidCount"),
            "applyCount": seed.get("applyCount"),
        },
        "final_core": {
            "id": seed.get("id"),
            "source_item_id": pick_first(seed.get("source_item_id"), seed.get("item_id"), seed.get("id")),
            "source_url": pick_first(final_url, seed.get("url"), seed.get("source_url")),
            "title": seed.get("title"),
            "is_processed": False,
            "detail_captured": True,
        },
        "description_data": description_data,
        "artifacts": {
            "seed_json_path": str(item_dir / "seed.json"),
            "detail_html_path": str(item_dir / "detail.html"),
            "description_json_path": str(item_dir / "description-data.json"),
            "description_text_path": description_data.get("text_path"),
            "selected_json_path": str(item_dir / "selected.json"),
        },
    }

__all__ = ('risk_aliases', 'build_description_audit', 'selected_summary', 'raw_detail_summary')
