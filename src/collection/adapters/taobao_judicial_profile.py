from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Mapping, MutableMapping, Sequence


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
