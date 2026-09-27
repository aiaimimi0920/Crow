"""Legacy auction price callbacks; intentionally distinct from AVM normalization."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Protocol


class AuctionPriceHost(Protocol):
    parse_price: Callable[[object], float | None]


@dataclass(frozen=True)
class AuctionPricePolicy:
    host: AuctionPriceHost

    __all__: ClassVar[list[str]] = [
        "parse_price",
        "get_starting_price",
        "get_predicted_price",
        "compute_margin",
        "_safe_int",
    ]

    def parse_price(self, raw_value: object) -> float | None:
        if raw_value is None:
            return None
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        if not isinstance(raw_value, str):
            return None
        text = raw_value.strip().replace(",", "")
        if not text:
            return None
        multiplier = 1.0
        if "亿" in text:
            multiplier = 100000000.0
        elif "万元" in text or "万" in text:
            multiplier = 10000.0
        numeric_text = re.sub(r"[^0-9.]", "", text)
        if not numeric_text:
            return None
        try:
            return float(numeric_text) * multiplier
        except ValueError:
            return None

    def get_starting_price(self, item: dict[str, object]) -> float | None:
        return self.host.parse_price(
            item.get("starting_price")
        ) or self.host.parse_price(item.get("起拍价格"))

    def get_predicted_price(self, item: dict[str, object]) -> float | None:
        return (
            self.host.parse_price(item.get("predicted_price"))
            or self.host.parse_price(item.get("估值"))
            or self.host.parse_price(item.get("市场评估价"))
            or self.host.parse_price(item.get("evaluation_price"))
            or self.host.parse_price(item.get("transaction_price"))
            or self.host.parse_price(item.get("成交价格"))
        )

    def compute_margin(
        self, predicted_price: float | None, starting_price: float | None
    ) -> float | None:
        if not predicted_price or predicted_price <= 0 or starting_price is None:
            return None
        return (predicted_price - starting_price) / predicted_price

    def _safe_int(self, value: object) -> int | None:
        parsed = self.host.parse_price(value)
        if parsed is None:
            return None
        try:
            return int(parsed)
        except (TypeError, ValueError):
            return None
