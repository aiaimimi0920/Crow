"""Explicit, bounded recovery of blocked collection work; never rewrite listings."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from sqlalchemy import select

from .models import CollectionSeedItem, PropertyAudit, PropertyListing
from .repository_context import _coerce_naive_utc, _resolve_collection_artifact_path, _utc_now

if TYPE_CHECKING:
    from .repository import PropertyRepository


def requeue_blocked_items(
    repository: PropertyRepository,
    item_ids: Iterable[str],
    *,
    recovery_id: str,
    apply: bool = False,
    max_rounds: int = 1,
) -> list[dict[str, object]]:
    """Dry-run by default. Missing raw evidence requires recapture, not another AI call.

    Run this on the consuming node with its real artifact mounts. Existing attempts
    and errors are retained in the recovery receipt before a new bounded cycle.
    """
    ids = sorted({str(value) for value in item_ids})
    if (not recovery_id.strip() or recovery_id != recovery_id.strip()
            or any(not value.strip() for value in ids) or len(ids) > 100 or not 1 <= max_rounds <= 3):
        raise ValueError("Recovery requires an ID, at most 100 items, and 1..3 rounds")
    if not repository.enabled:
        return []
    repository.initialize()
    now = _utc_now()
    results: list[dict[str, object]] = []
    with repository.session_factory.begin() as session:
        for item_id in ids:
            row = session.scalars(
                select(CollectionSeedItem)
                .where(CollectionSeedItem.item_id == item_id)
                .with_for_update(skip_locked=True)
            ).first()
            result: dict[str, object] = {"item_id": item_id, "applied": False}
            results.append(result)
            if row is None:
                result["skip"] = "missing_or_locked"
                continue
            if row.status not in {"analysis_blocked", "detail_blocked"}:
                result["skip"] = "not_blocked"
                continue
            lease_until = _coerce_naive_utc(row.detail_lease_until)
            if (lease_until and lease_until > now) or (row.detail_leased_by and not lease_until):
                result["skip"] = "active_or_unknown_lease"
                continue
            payload = dict(row.source_payload or {})
            history = payload.get("_blocked_recovery") or []
            if not isinstance(history, list) or any(not isinstance(entry, dict) for entry in history):
                result["skip"] = "invalid_recovery_history"
                continue
            if any(entry.get("recovery_id") == recovery_id for entry in history):
                result["skip"] = "already_recovered"
                continue
            if len(history) >= max_rounds:
                result["skip"] = "recovery_limit"
                continue
            audit = session.get(PropertyAudit, item_id)
            processed = audit is not None and audit.is_processed is True
            completed = processed and session.scalar(
                select(PropertyListing.item_id)
                .join(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(PropertyListing.item_id == item_id,
                       PropertyListing.is_deleted.is_(False),
                       PropertyAudit.detail_captured.is_(True),
                       repository._analysis_ready_filter())
            ) is not None
            if processed and not completed:
                result["skip"] = "processed_requires_review"
                continue
            artifacts = repository._seed_artifacts_from_row(row)
            raw_path = _resolve_collection_artifact_path(artifacts.get("detail_html_path"))
            try:
                has_raw = bool(raw_path and Path(raw_path).is_file() and Path(raw_path).stat().st_size > 0)
            except OSError:
                result["skip"] = "artifact_unreadable"
                continue
            analyze = row.status == "analysis_blocked" and has_raw
            target = "detail_completed" if completed else "analysis_failed" if analyze else "detail_failed"
            result.update({"previous_status": row.status, "target_status": target,
                           "reason": "existing_completed_data" if completed else
                           "raw_available" if analyze else "recapture_required"})
            if not apply:
                continue
            receipt = {
                "recovery_id": recovery_id,
                "recovered_at": now.isoformat(),
                "previous_status": row.status,
                "previous_error": row.detail_last_error,
                "detail_attempts": row.detail_attempt_count,
                "analysis_attempts": payload.get("_analysis_attempt_count", 0),
                "target_status": target,
            }
            payload["_blocked_recovery"] = [*history, receipt]
            # Preserve original, portable paths and prior artifacts even on recapture.
            if completed:
                row.detail_completed_at = row.detail_completed_at or audit.updated_at or now
                row.detail_last_error = None
            elif analyze:
                payload["_raw_detail_artifacts"] = {
                    **(payload.get("_raw_detail_artifacts") or {}),
                    **{key: value for key, value in artifacts.items() if value},
                }
            else:
                row.detail_attempt_count = 0
            if not completed:
                payload["_analysis_attempt_count"] = 0
            row.source_payload = payload
            row.status = target
            row.detail_leased_by = None
            row.detail_lease_until = None
            row.updated_at = now
            result["applied"] = True
    return results
