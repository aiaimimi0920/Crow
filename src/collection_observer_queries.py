"""Read-only collection observer queries with an explicit repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from src.storage.repository import PropertyRepository


def query_int(
    query: dict[str, list[str]], key: str, default: int, *, minimum: int, maximum: int
) -> int:
    try:
        values = query.get(key)
        value = int(values[0]) if values else default
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def items(
    query: dict[str, list[str]], *, repository: PropertyRepository
) -> dict[str, object]:
    stage = str((query.get("stage") or ["links"])[0] or "links").strip().lower()
    if stage not in {"links", "details", "analysis"}:
        stage = "links"
    limit = query_int(query, "limit", 100, minimum=1, maximum=500)
    offset = query_int(query, "offset", 0, minimum=0, maximum=1_000_000)
    location_code = str((query.get("location_code") or [""])[0] or "").strip()
    if not repository.enabled or not hasattr(repository, "collection_observer_items"):
        return {
            "stage": stage,
            "limit": limit,
            "offset": offset,
            "location_code": location_code or None,
            "total": 0,
            "items": [],
            "db_mode": repository.enabled,
        }
    payload = repository.collection_observer_items(
        stage=stage,
        limit=limit,
        offset=offset,
        location_code=location_code or None,
    )
    payload["location_code"] = location_code or payload.get("location_code")
    payload["db_mode"] = repository.enabled
    return cast("dict[str, object]", payload)


def regions(
    query: dict[str, list[str]], *, repository: PropertyRepository
) -> dict[str, object]:
    stage = str((query.get("stage") or ["links"])[0] or "links").strip().lower()
    if stage not in {"links", "details", "analysis"}:
        stage = "links"
    if not repository.enabled or not hasattr(repository, "collection_observer_regions"):
        return {
            "ok": True,
            "stage": stage,
            "regions": [],
            "db_mode": repository.enabled,
        }
    payload = repository.collection_observer_regions(stage=stage)
    payload["db_mode"] = repository.enabled
    return cast("dict[str, object]", payload)


def item(
    query: dict[str, list[str]], *, repository: PropertyRepository
) -> dict[str, object]:
    item_id = str((query.get("item_id") or [""])[0] or "").strip()
    max_chars = query_int(query, "max_chars", 100_000, minimum=1, maximum=1_000_000)
    if not item_id:
        return {"found": False, "error": "item_id is required", "item_id": ""}
    if not repository.enabled or not hasattr(
        repository, "collection_observer_item_detail"
    ):
        return {
            "found": False,
            "item_id": item_id,
            "item": None,
            "occurrences": [],
            "artifacts": {},
            "db_mode": repository.enabled,
        }
    payload = repository.collection_observer_item_detail(item_id, max_chars=max_chars)
    payload["db_mode"] = repository.enabled
    return cast("dict[str, object]", payload)
