"""Collection observer mutations with an explicitly selected repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from src.storage.repository import PropertyRepository


def reanalysis(
    payload: dict[str, object], *, repository: PropertyRepository
) -> dict[str, object]:
    item_id = str(payload.get("item_id") or "").strip()
    reason = (
        str(payload.get("reason") or "operator_requested").strip()
        or "operator_requested"
    )
    if not item_id:
        return {"ok": False, "error": "item_id is required", "item_id": ""}
    if not repository.enabled or not hasattr(
        repository, "requeue_seed_detail_analysis"
    ):
        return {
            "ok": False,
            "item_id": item_id,
            "error": "database repository is not available",
            "db_mode": repository.enabled,
        }
    result = repository.requeue_seed_detail_analysis(item_id, reason=reason)
    result["db_mode"] = repository.enabled
    return cast("dict[str, object]", result)


def manual_update(
    payload: dict[str, object], *, repository: PropertyRepository
) -> dict[str, object]:
    item_id = str(payload.get("item_id") or "").strip()
    updates = payload.get("updates")
    if not item_id:
        return {"ok": False, "error": "item_id is required", "item_id": ""}
    if not isinstance(updates, dict) or not updates:
        return {
            "ok": False,
            "item_id": item_id,
            "error": "updates must be a non-empty object",
        }
    if not repository.enabled or not hasattr(repository, "manual_update_flat_item"):
        return {
            "ok": False,
            "item_id": item_id,
            "error": "database repository is not available",
            "db_mode": repository.enabled,
        }
    result = repository.manual_update_flat_item(item_id, updates)
    result["db_mode"] = repository.enabled
    return cast("dict[str, object]", result)


def reset_region_links(
    payload: dict[str, object], *, repository: PropertyRepository
) -> dict[str, object]:
    location_code = str(payload.get("location_code") or "").strip()
    if not location_code:
        return {"ok": False, "error": "location_code is required", "location_code": ""}
    if not repository.enabled or not hasattr(repository, "reset_seed_link_region"):
        return {
            "ok": False,
            "location_code": location_code,
            "error": "database repository is not available",
            "db_mode": repository.enabled,
        }
    result = repository.reset_seed_link_region(location_code)
    result["db_mode"] = repository.enabled
    return cast("dict[str, object]", result)
