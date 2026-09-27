"""Judicial source facts used by detail maintenance."""

from __future__ import annotations


def needs_risk_enrich(row: dict[str, object]) -> bool:
    risk_payload = row.get("avm_risk_features")
    if not isinstance(risk_payload, dict):
        return True
    return not any(
        risk_payload.get(key) not in (None, "", "UNK")
        for key in (
            "is_occupied",
            "has_long_lease",
            "clear_delivery",
            "tax_burden",
            "is_fractional_share",
        )
    )


def merge_risk_features(row: dict[str, object], extracted: dict[str, object]) -> None:
    row["avm_risk_features"] = extracted
    for key in (
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
        "evaluation_price",
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
    ):
        value = extracted.get(key)
        if value not in (None, "", "UNK"):
            row[key] = value
