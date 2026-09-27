"""Legacy auction field aliases and explicit structured-record resynchronization."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol

FLAT_OVERRIDE_ALIASES = {
    "status": "status",
    "状态": "status",
    "交易时间": "auction_date",
    "auction_date": "auction_date",
    "成交价格": "transaction_price",
    "currentPrice": "transaction_price",
    "transaction_price": "transaction_price",
    "起拍价格": "starting_price",
    "initialPrice": "starting_price",
    "starting_price": "starting_price",
    "保证金": "deposit",
    "deposit": "deposit",
    "竞拍人数": "apply_count",
    "applyCount": "apply_count",
    "apply_count": "apply_count",
    "出价次数": "bid_count",
    "bidCount": "bid_count",
    "bid_count": "bid_count",
    "出价人数": "bidder_count",
    "bidderCount": "bidder_count",
    "bidder_count": "bidder_count",
    "地点": "full_address",
    "完整地址": "full_address",
    "full_address": "full_address",
    "城市": "city",
    "city": "city",
    "区": "district",
    "district": "district",
    "最靠近商圈": "business_area",
    "business_area": "business_area",
    "所属小区": "community_name",
    "community_name": "community_name",
    "纬度": "latitude",
    "latitude": "latitude",
    "经度": "longitude",
    "longitude": "longitude",
    "建筑面积": "area_sqm",
    "建设面积": "area_sqm",
    "area_sqm": "area_sqm",
    "产权建筑面积": "gross_area_sqm",
    "原始建筑面积": "gross_area_sqm",
    "gross_area_sqm": "gross_area_sqm",
    "产权份额比例": "ownership_share_ratio",
    "ownership_share_ratio": "ownership_share_ratio",
}


class AuctionPatchHost(Protocol):
    _FLAT_OVERRIDE_ALIAS_MAP: Mapping[str, str]


@dataclass(frozen=True)
class AuctionRecordPatch:
    host: AuctionPatchHost

    __all__: ClassVar[list[str]] = [
        "_reset_structured_sections_for_resync",
        "_apply_flat_override_patch",
    ]

    def _reset_structured_sections_for_resync(self, item: dict[str, object]) -> None:
        for key in (
            "source",
            "archive",
            "auction",
            "location",
            "property",
            "legal_context",
            "risk_flags",
            "audit",
        ):
            item.pop(key, None)

    def _apply_flat_override_patch(
        self, item: dict[str, object], patch: Mapping[str, object]
    ) -> None:
        for patch_key, target_key in self.host._FLAT_OVERRIDE_ALIAS_MAP.items():
            if patch_key in patch and patch.get(patch_key) not in (None, ""):
                item[target_key] = patch.get(patch_key)
