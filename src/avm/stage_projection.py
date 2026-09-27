"""Existing analysis readiness projection, explicitly requested by legacy readers."""

from collections.abc import Callable, Mapping
from typing import cast

from src.collection.readiness import (
    GENERIC_PRODUCT_MODEL_VERSION,
    default_analysis_missing_fields,
    uses_generic_product_analysis,
)


def _model_version() -> str:
    try:
        from src.avm.service import MODEL_VERSION

        return cast(str, MODEL_VERSION)
    except Exception:
        return "avm_multidim_v1"


def derive_analysis_state(
    record: dict[str, object],
    detail_status: str | None,
    *,
    event_type: str | None = None,
    existing: Mapping[str, object] | None = None,
    analysis_requirements: Callable[[Mapping[str, object], str | None], list[str]]
    | None = None,
    analysis_model_version: str | None = None,
) -> dict[str, object]:
    existing = existing or {}
    requirements = analysis_requirements or default_analysis_missing_fields
    missing_fields = requirements(record, detail_status)
    ready = len(missing_fields) == 0
    status = "ready" if ready else "not_ready"
    if event_type == "mark_deleted":
        status = "invalid"
        ready = False
    model_version = analysis_model_version or existing.get("analysis_model_version")
    if ready:
        model_version = (
            GENERIC_PRODUCT_MODEL_VERSION
            if analysis_model_version is None and uses_generic_product_analysis(record)
            else analysis_model_version or _model_version()
        )
    return {
        "analysis_status": status,
        "analysis_ready": ready,
        "analysis_missing_fields": missing_fields,
        "analysis_last_scored_at": existing.get("analysis_last_scored_at"),
        "analysis_model_version": model_version,
    }
