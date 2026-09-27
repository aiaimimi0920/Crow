from __future__ import annotations

MODEL_VERSION = "avm_multidim_v1"
MAX_CANDIDATE_POOL = 5000
GLOBAL_RECENT_CANDIDATES = 5000

RISK_IMPACT_MAP = {
    "is_occupied": (-0.12, "存在占用，处置周期与交付风险上升"),
    "has_long_lease": (-0.14, "长期租约会拉低可回收价值"),
    "is_restricted_purchase": (-0.03, "限购会压缩潜在买家池并影响流动性"),
    "property_fee_owed": (-0.03, "欠费可能抬升实际支付总价"),
    "tax_is_company_owned": (-0.06, "企业产权可能带来额外税费"),
    "is_fractional_share": (-0.17, "部分产权显著影响流动性"),
    "has_lease_before_mortgage": (0.04, "先抵后租具备一定套利修正"),
}

__all__ = [
    "GLOBAL_RECENT_CANDIDATES",
    "MAX_CANDIDATE_POOL",
    "MODEL_VERSION",
    "RISK_IMPACT_MAP",
]
