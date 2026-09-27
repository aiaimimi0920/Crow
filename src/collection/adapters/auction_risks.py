"""Auction risk aliases and legacy screening response policy."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol, cast


class AuctionRiskHost(Protocol):
    RISK_ALIAS_KEYS: Iterable[str]
    MALIGNANT_RISK_LABELS: Mapping[str, str]

    def _get_risk_payload(self, item: Mapping[str, object]) -> dict[str, object]: ...
    def _risk_value(self, item: Mapping[str, object], key: str) -> object: ...
    def get_predicted_price(self, item: Mapping[str, object]) -> float | None: ...
    def get_starting_price(self, item: Mapping[str, object]) -> float | None: ...
    def compute_margin(
        self, predicted_price: float | None, starting_price: float | None
    ) -> float | None: ...
    def extract_risk_signals(self, item: Mapping[str, object]) -> list[str]: ...


@dataclass(frozen=True)
class AuctionRiskPolicy:
    host: AuctionRiskHost

    __all__: ClassVar[list[str]] = [
        "_get_risk_payload",
        "_risk_value",
        "sync_avm_risk_aliases",
        "extract_risk_signals",
        "build_avm_result",
    ]

    def _get_risk_payload(self, item: Mapping[str, object]) -> dict[str, object]:
        payload = item.get("avm_risk_features")
        return cast(dict[str, object], payload) if isinstance(payload, dict) else {}

    def _risk_value(self, item: Mapping[str, object], key: str) -> object:
        if item.get(key) is not None:
            return item.get(key)
        return self.host._get_risk_payload(item).get(key)

    def sync_avm_risk_aliases(self, item: dict[str, object]) -> dict[str, object]:
        risk_payload = self.host._get_risk_payload(item)
        if not risk_payload:
            return item
        for key in self.host.RISK_ALIAS_KEYS:
            value = risk_payload.get(key)
            if value in (None, ""):
                continue
            item.setdefault(key, value)
        if risk_payload.get("community_name") and not item.get("所属小区"):
            item["所属小区"] = risk_payload["community_name"]
        if risk_payload.get("housing_type") and not item.get("housing_type"):
            item["housing_type"] = risk_payload["housing_type"]
        return item

    def extract_risk_signals(self, item: Mapping[str, object]) -> list[str]:
        major_risks = []
        for key, label in self.host.MALIGNANT_RISK_LABELS.items():
            if self.host._risk_value(item, key) is True:
                major_risks.append(label)
        if self.host._risk_value(item, "clear_delivery") is False:
            major_risks.append("法院不负责清场交付")
        if self.host._risk_value(item, "land_right_type") == "划拨":
            major_risks.append("土地性质为划拨")
        return major_risks

    def build_avm_result(
        self, item_id: object, item: Mapping[str, object]
    ) -> dict[str, object]:
        predicted_price = self.host.get_predicted_price(item)
        starting_price = self.host.get_starting_price(item)
        margin = self.host.compute_margin(predicted_price, starting_price)
        major_risks = self.host.extract_risk_signals(item)
        return {
            "id": str(item_id),
            "predicted_price": predicted_price,
            "starting_price": starting_price,
            "margin": margin,
            "is_malignant_risk": len(major_risks) > 0,
            "major_risks": major_risks,
            "risk_summary": "；".join(major_risks)
            if major_risks
            else "未发现恶性风控标签",
        }
