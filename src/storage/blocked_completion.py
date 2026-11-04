"""Reconcile collection completion from final evidence, not downstream AVM readiness."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from .models import PropertyIngestEvent, PropertyListing
from .repository_context import _resolve_collection_artifact_path


def existing_collection_completion(session, repository, row, audit) -> bool:
    if (
        audit is None
        or audit.is_processed is not True
        or audit.detail_captured is not True
    ):
        return False
    listing = session.get(PropertyListing, row.item_id)
    if listing is None or listing.is_deleted is not False:
        return False
    path = _resolve_collection_artifact_path(
        repository._seed_artifacts_from_row(row).get("final_json_path")
    )
    if not path:
        return False
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return False
    if not isinstance(payload, dict) or not payload:
        return False
    identities = [payload[key] for key in ("id", "item_id") if key in payload]
    if not identities or any(str(value) != row.item_id for value in identities):
        return False
    if (
        payload.get("is_processed") is not True
        or payload.get("detail_captured") is not True
    ):
        return False
    events = session.scalars(
        select(PropertyIngestEvent).where(
            PropertyIngestEvent.item_id == row.item_id,
            PropertyIngestEvent.event_type.in_(
                ("detail_analysis_completed", "detail_worker_completed")
            ),
        )
    )
    for event in events:
        receipt = event.event_payload or {}
        if not isinstance(receipt, dict):
            continue
        if str(receipt.get("item_id")) != row.item_id:
            continue
        if _resolve_collection_artifact_path(receipt.get("final_json_path")) != path:
            continue
        module_b = receipt.get("analysis_module_b")
        if module_b is not None and not isinstance(module_b, dict):
            continue
        if (
            isinstance(module_b, dict)
            and module_b.get("mode") == "primary"
            and module_b.get("status") != "finalized"
        ):
            continue
        return True
    return False
