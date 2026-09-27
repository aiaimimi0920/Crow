"""Collected auction risk aliases shared by ingestion and legacy readers."""

MALIGNANT_RISK_LABELS = {
    "is_haunted": "疑似凶宅/刑事案件",
    "is_occupied": "房屋疑似被占用未腾空",
    "has_long_lease": "存在长租约风险",
    "is_fractional_share": "标的为部分产权",
    "tax_is_company_owned": "企业产权潜在高税费",
}

RISK_ALIAS_KEYS = (
    "community_name",
    "build_year",
    "total_floors",
    "floor_level",
    "has_elevator",
    "orientation",
    "land_right_type",
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "tax_burden",
    "is_haunted",
    "housing_type",
    "has_keys",
    "property_fee_owed",
    "special_school_tag",
    "layout",
    "is_restricted_purchase",
    "includes_parking",
    "is_fractional_share",
    "tax_is_company_owned",
    "has_lease_before_mortgage",
    "extraction_confidence",
    "evidence_span",
    "evidence_source",
    "extraction_version",
)
