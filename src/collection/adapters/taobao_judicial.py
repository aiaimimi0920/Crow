from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Mapping, MutableMapping, Sequence

from ..contracts import NumberParser, Record
from ..record_schema import sync_collection_record
from ..search_task_policy import SearchTaskPolicy, TaobaoJudicialSearchTaskPolicy
from ..seed_list_parser import SeedListParser, TaobaoSeedListParser
from ..seed_scan_policy import SeedScanPolicy, TaobaoJudicialSeedScanPolicy
from .generic_product import GenericProductAdapter

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
        record.setdefault("source_platform", self.source_platform)
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


@dataclass(frozen=True)
class TaobaoJudicialAnalysisProfile:
    money_fields = frozenset(
        {
            "市场评估价",
            "起拍价格",
            "成交价格",
            "保证金",
            "evaluation_price",
            "starting_price",
            "transaction_price",
            "deposit",
        }
    )
    area_fields = frozenset(
        {
            "建筑面积",
            "产权建筑面积",
            "area_sqm",
            "gross_area_sqm",
            "interior_area_sqm",
            "land_area_sqm",
        }
    )
    ratio_fields = frozenset({"产权份额比例", "ownership_share_ratio"})
    count_fields = frozenset(
        {
            "竞拍人数",
            "出价次数",
            "出价人数",
            "围观人数",
            "提醒人数",
            "浏览次数",
            "apply_count",
            "bid_count",
            "bidder_count",
            "watch_count",
            "reminder_count",
            "view_count",
            "build_year",
            "total_floors",
        }
    )
    boolean_fields = frozenset(
        {
            "是否成交",
            "is_occupied",
            "has_long_lease",
            "clear_delivery",
            "property_fee_owed",
            "is_restricted_purchase",
            "is_fractional_share",
            "tax_is_company_owned",
            "has_lease_before_mortgage",
            "has_elevator",
            "includes_parking",
            "has_keys",
            "is_haunted",
            "special_school_tag",
        }
    )
    datetime_fields = frozenset(
        {"开拍时间", "交易时间", "auction_date", "auction_start_time"}
    )
    derived_fields = frozenset({"单价", "unit_price"})
    system_fields = frozenset(
        {
            "id",
            "item_id",
            "唯一id",
            "source_item_id",
            "source_platform",
            "原始网站",
            "source_url",
            "url",
            "标题",
            "title",
            "source_title",
            "is_processed",
            "detail_captured",
            "status",
            "auction_date",
            "currentPrice",
            "initialPrice",
            "applyCount",
            "bidCount",
            "bidderCount",
            "deposit",
            "latitude",
            "longitude",
            "纬度",
            "经度",
            "coordinate_source",
            "extraction_confidence",
            "evidence_span",
            "evidence_source",
            "extraction_version",
            "avm_risk_features",
        }
    )
    high_risk_fields = frozenset(
        set(money_fields)
        | set(area_fields)
        | set(ratio_fields)
        | set(datetime_fields)
        | {
            "是否成交",
            "法院名称",
            "案号",
            "is_occupied",
            "has_long_lease",
            "clear_delivery",
            "tax_burden",
            "property_fee_owed",
            "is_restricted_purchase",
            "is_fractional_share",
            "tax_is_company_owned",
            "has_lease_before_mortgage",
        }
    )
    field_keywords = {
        "市场评估价": ("市场评估价", "评估价", "评估价格"),
        "起拍价格": ("起拍价格", "起拍价", "initialPrice"),
        "成交价格": ("成交价格", "成交价", "拍下价", "currentPrice"),
        "保证金": ("保证金", "deposit"),
        "开拍时间": ("开拍时间", "startTime"),
        "交易时间": ("交易时间", "auction_date", "结束时间"),
        "是否成交": ("是否成交", "status"),
        "竞拍人数": ("竞拍人数", "报名人数", "applyCount"),
        "出价次数": ("出价次数", "bidCount"),
        "出价人数": ("出价人数", "bidUserNumber"),
        "围观人数": ("围观人数", "围观", "watchCount", "pv"),
        "提醒人数": ("提醒人数", "提醒", "remindCount"),
        "浏览次数": ("浏览次数", "浏览", "viewCount"),
        "地点": ("地点", "地址", "address"),
        "完整地址": ("完整地址", "地址", "address"),
        "所属小区": ("所属小区", "小区", "楼盘", "community"),
        "省份": ("省份", "省"),
        "城市": ("城市", "市"),
        "区": ("区县", "行政区", "区"),
        "最靠近商圈": ("商圈", "板块"),
        "建筑面积": ("建筑面积", "description_area_sqm", "building_area"),
        "产权建筑面积": ("产权建筑面积", "原始产权建筑面积"),
        "产权份额比例": ("产权份额比例", "产权份额", "所有权份额"),
        "法院名称": ("法院名称", "执行法院", "法院"),
        "案号": ("案号",),
        "is_occupied": ("占用", "占有人", "腾退"),
        "has_long_lease": ("租赁", "租约", "承租"),
        "clear_delivery": ("腾退", "交付", "清场"),
        "tax_burden": ("税费", "税款", "税金"),
        "property_fee_owed": ("物业费", "欠费"),
        "is_restricted_purchase": ("限购", "购房资格"),
        "is_fractional_share": ("份额", "产权"),
        "tax_is_company_owned": ("公司所有", "企业所有", "税费"),
        "has_lease_before_mortgage": ("租赁", "抵押"),
    }

    def adjudication_prompt(
        self,
        *,
        item_id: str,
        conflicts: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
        source_text: str,
    ) -> str:
        return f"""
# Role
你是法拍房分析模块 B 的证据仲裁模型。你只处理三份独立分析结果中的冲突字段。

# Hard rules
1. 只能返回下方 conflicts 中已有的字段，禁止修改任何已锁定字段。
2. 每个非空结论都必须引用【原始证据】中的原文片段；不能只按多数票决定。
3. 可以选择任一候选值，也可以在原文明确支持时给出新值。
4. 原文不足、含糊或互相矛盾时，value 必须为 null，decision 必须为 needs_review。
5. “未说明”不等于 false；禁止根据常识补全租赁、占用、税费、腾退、面积或价格。
6. 仅输出 JSON，不要输出 Markdown 或解释性前后缀。

# Output schema
{{"decisions": {{"字段路径": {{"value": null, "decision": "candidate_1|candidate_2|candidate_3|new|needs_review", "evidence": "原文中的短片段；value 非空时必填", "confidence": 0.0}}}}}}

# Item
{item_id}

# Three independent module A results
{json.dumps(list(candidates), ensure_ascii=False, sort_keys=True)}

# Conflicts
{json.dumps(conflicts, ensure_ascii=False, sort_keys=True)}

# 原始证据
{source_text[:100000]}
""".strip()

    def derive_final_fields(self, field_values: MutableMapping[str, Any]) -> None:
        transaction_price = _decimal(field_values.get("成交价格"))
        area = _decimal(field_values.get("建筑面积"))
        if transaction_price is not None and area is not None and area > 0:
            field_values["单价"] = float(
                (transaction_price / area).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            )
        else:
            field_values["单价"] = 0


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    multiplier = Decimal("1")
    if "亿" in text:
        multiplier = Decimal("100000000")
    elif "万" in text:
        multiplier = Decimal("10000")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    try:
        return Decimal(match.group(0)) * multiplier
    except InvalidOperation:
        return None
