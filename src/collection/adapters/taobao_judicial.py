from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping

from ..contracts import NumberParser, Record
from ..record_schema import sync_collection_record
from ..search_task_policy import SearchTaskPolicy, TaobaoJudicialSearchTaskPolicy
from ..seed_list_parser import SeedListParser, TaobaoSeedListParser
from ..seed_scan_policy import SeedScanPolicy, TaobaoJudicialSeedScanPolicy
from .generic_product import GenericProductAdapter
from .taobao_judicial_profile import (
    TaobaoJudicialAnalysisProfile as TaobaoJudicialAnalysisProfile,
)

_SEED_FIELDS_TO_PRESERVE = (
    "title",
    "source_title",
    "url",
    "source_url",
    "source_item_id",
    "auction_date",
    "交易时间",
    "currentPrice",
    "initialPrice",
    "transaction_price",
    "starting_price",
    "成交价格",
    "起拍价格",
    "applyCount",
    "竞拍人数",
    "apply_count",
    "bidCount",
    "bid_count",
    "出价次数",
    "bidderCount",
    "bidder_count",
    "出价人数",
    "deposit",
    "保证金",
    "地点",
    "full_address",
    "完整地址",
    "城市",
    "区",
    "latitude",
    "longitude",
    "纬度",
    "经度",
    "coordinate_source",
    "auction_round",
    "housing_type",
    "status",
    "是否成交",
)


def _has_value(value: Any) -> bool:
    return value not in (None, "", [])


@dataclass(frozen=True)
class TaobaoJudicialAuctionAdapter(GenericProductAdapter):
    """Compatibility adapter for the existing Taobao judicial-auction workflow."""

    source_platform: str = "taobao_sf"
    collects_avm_risk: bool = True
    bootstraps_legacy_search_tasks: bool = True

    @property
    def search_task_policy(self) -> SearchTaskPolicy:
        return TaobaoJudicialSearchTaskPolicy()

    @property
    def seed_scan_policy(self) -> SeedScanPolicy:
        return TaobaoJudicialSeedScanPolicy()

    @property
    def analysis_profile(self) -> TaobaoJudicialAnalysisProfile:
        return TaobaoJudicialAnalysisProfile()

    def create_seed_list_parser(self, legacy_probe: Any) -> SeedListParser:
        return TaobaoSeedListParser(legacy_probe)

    def build_seed_record(
        self,
        item: Mapping[str, Any],
        *,
        parse_number: NumberParser,
        safe_int: NumberParser,
    ) -> Record:
        deal_price = parse_number(item.get("currentPrice")) or parse_number(
            item.get("成交价格")
        )
        starting_price = parse_number(item.get("initialPrice")) or parse_number(
            item.get("起拍价格")
        )
        apply_count = safe_int(item.get("applyCount")) or safe_int(item.get("竞拍人数"))
        bid_count = safe_int(item.get("bidCount")) or safe_int(item.get("出价次数"))
        bidder_count = (
            safe_int(item.get("bidderCount"))
            or safe_int(item.get("bidder_count"))
            or safe_int(item.get("出价人数"))
        )
        deposit = parse_number(item.get("deposit")) or parse_number(item.get("保证金"))
        auction_date = str(item.get("auction_date", "") or "").strip()
        auction_start_time = str(
            item.get("auction_start_time", "") or item.get("startTime", "") or ""
        ).strip()
        full_address = (
            item.get("full_address")
            or item.get("完整地址")
            or item.get("location")
            or item.get("地点")
        )
        watch_count = (
            safe_int(item.get("watchCount"))
            or safe_int(item.get("watch_count"))
            or safe_int(item.get("围观人数"))
        )
        reminder_count = (
            safe_int(item.get("remindCount"))
            or safe_int(item.get("reminder_count"))
            or safe_int(item.get("提醒人数"))
        )
        view_count = (
            safe_int(item.get("viewCount"))
            or safe_int(item.get("view_count"))
            or safe_int(item.get("浏览次数"))
        )

        stub = {
            "id": self.item_id(item),
            "title": item.get("title"),
            "source_title": item.get("title"),
            "source_platform": item.get("source_platform") or self.source_platform,
            "url": item.get("url"),
            "source_url": item.get("url"),
            "地点": full_address,
            "full_address": full_address,
            "完整地址": full_address,
            "城市": item.get("city"),
            "区": item.get("district"),
            "end": item.get("end"),
            "status": "done",
            "is_processed": False,
            "auction_date": auction_date,
            "交易时间": auction_date or None,
            "auction_start_time": auction_start_time or None,
            "开拍时间": auction_start_time or None,
            "currentPrice": deal_price,
            "initialPrice": starting_price,
            "transaction_price": deal_price,
            "starting_price": starting_price,
            "成交价格": deal_price,
            "起拍价格": starting_price,
            "applyCount": apply_count,
            "竞拍人数": apply_count,
            "apply_count": apply_count,
            "bidCount": bid_count,
            "bid_count": bid_count,
            "出价次数": bid_count,
            "bidderCount": bidder_count,
            "bidder_count": bidder_count,
            "出价人数": bidder_count,
            "watchCount": watch_count,
            "watch_count": watch_count,
            "围观人数": watch_count,
            "remindCount": reminder_count,
            "reminder_count": reminder_count,
            "提醒人数": reminder_count,
            "viewCount": view_count,
            "view_count": view_count,
            "浏览次数": view_count,
            "deposit": deposit,
            "保证金": deposit,
            "latitude": parse_number(item.get("latitude"))
            if item.get("latitude") is not None
            else None,
            "longitude": parse_number(item.get("longitude"))
            if item.get("longitude") is not None
            else None,
            "纬度": parse_number(item.get("latitude"))
            if item.get("latitude") is not None
            else None,
            "经度": parse_number(item.get("longitude"))
            if item.get("longitude") is not None
            else None,
            "coordinate_source": item.get("coordinate_source"),
            "auction_round": safe_int(item.get("auction_round")),
            "housing_type": item.get("housing_type"),
            "source_item_id": self.item_id(item),
            "list_payload_path": item.get("list_payload_path"),
            "source_page_url": item.get("source_page_url") or item.get("page_url"),
        }
        return sync_collection_record(
            {key: value for key, value in stub.items() if value not in (None, "")}
        )

    def accepts_seed(self, item: Mapping[str, Any], record: Mapping[str, Any]) -> bool:
        del record
        status = str(item.get("status", "")).lower()
        return (
            status in {"done", "成交"}
            or item.get("是否成交") is True
            or str(item.get("outcome", "")).lower() == "成交"
        )

    def sync_record(self, record: MutableMapping[str, Any]) -> None:
        sync_collection_record(record)

    def partition_key(self, record: Mapping[str, Any]) -> str:
        return str(record.get("auction_date") or "").split(" ", 1)[0] or "unknown"

    def prepare_detail_record(
        self,
        record: MutableMapping[str, Any],
        *,
        existing: Mapping[str, Any],
        item_id: str,
    ) -> None:
        self.preserve_seed_values(record, existing)

        if record.get("交易时间") and not record.get("auction_date"):
            record["auction_date"] = record.get("交易时间")
        if record.get("原始网站") and not record.get("source_url"):
            record["source_url"] = record.get("原始网站")
        record["id"] = int(item_id) if item_id.isdigit() else item_id
        record["source_item_id"] = item_id
        record["source_platform"] = (
            existing.get("source_platform") or self.source_platform
        )
        source_url = self.source_url(existing)
        if source_url:
            record["url"] = source_url
            record["source_url"] = source_url
            record["原始网站"] = source_url
        if "avm_risk_features" not in record:
            record["avm_risk_features"] = existing.get("avm_risk_features", {})
        if "avm_extraction_version" not in record:
            record["avm_extraction_version"] = existing.get("avm_extraction_version")

    def preserve_seed_values(
        self,
        record: MutableMapping[str, Any],
        existing: Mapping[str, Any],
    ) -> None:
        for key in _SEED_FIELDS_TO_PRESERVE:
            value = existing.get(key)
            if _has_value(value) and not _has_value(record.get(key)):
                record[key] = value

        aliases = {
            "标题": existing.get("title") or existing.get("source_title"),
            "source_title": existing.get("title") or existing.get("source_title"),
            "交易时间": existing.get("auction_date"),
            "成交价格": existing.get("currentPrice"),
            "起拍价格": existing.get("initialPrice"),
            "竞拍人数": existing.get("applyCount"),
            "出价次数": existing.get("bidCount"),
        }
        for key, value in aliases.items():
            if _has_value(value):
                record[key] = value

        status_text = str(record.get("status") or existing.get("status") or "").lower()
        if status_text in {"done", "成交", "ended", "finished", "结束"}:
            record["是否成交"] = True

    def accepts_detail(self, record: Mapping[str, Any]) -> bool:
        status = str(record.get("status", "")).lower()
        return (
            status in {"done", "成交", "ended", "finished", "结束"}
            or record.get("是否成交") is True
            or str(record.get("outcome", "")).lower()
            in {"成交", "success", "successful"}
        )

    def retry_reason(self, record: Mapping[str, Any]) -> str | None:
        area = record.get("建筑面积") or record.get("建设面积")
        return "建筑面积为空" if area in (None, 0, "0", "") else None

    def finalize_detail_record(self, record: MutableMapping[str, Any]) -> None:
        record["detail_captured"] = True
        record["is_processed"] = True
        sync_collection_record(record)

    def archive_date(self, record: Mapping[str, Any]) -> Any:
        return record.get("auction_date") or super().archive_date(record)

    def source_url(self, record: Mapping[str, Any]) -> str | None:
        value = record.get("source_url") or record.get("原始网站") or record.get("url")
        return str(value) if value else None

    def quality_summary(self, record: Mapping[str, Any]) -> str:
        return (
            f"area={record.get('建筑面积')}, "
            f"community={record.get('所属小区')}, unit_price={record.get('单价')}"
        )

    def location_prompt(self, *, address: str, title: str) -> str:
        return f"""
# Task
根据提供的房产地址和标题，推断该房产的详细位置信息。
请基于贝壳/链家等房产数据库的标准名称。

# Input
地址: {address}
标题: {title}

# Output JSON
{{
    "所属小区": "小区名称",
    "最靠近商圈": "商圈名称",
    "省份": "省",
    "城市": "市",
    "区": "区"
}}
如果某个字段无法推断，请填 null. 仅返回 JSON对象，不要包含 ```json 标记。
"""
