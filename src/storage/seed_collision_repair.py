from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    CollectionAnalysisRun,
    CollectionSeedItem,
    CollectionSeedOccurrence,
    PropertyIngestEvent,
    PropertyListing,
)
from .seed_collision_audit import REPORT_SCHEMA_VERSION, audit_seed_item_collision


RECEIPT_SCHEMA_VERSION = "seed_collision_repair_receipt_v1"


def _partition_seed_row(
    session: Session,
    partition: Mapping[str, Any],
) -> CollectionSeedItem:
    occurrence_ids = [
        int(move["occurrence_id"])
        for move in partition.get("occurrence_moves", [])
    ]
    occurrences = session.scalars(
        select(CollectionSeedOccurrence)
        .where(CollectionSeedOccurrence.id.in_(occurrence_ids))
        .order_by(CollectionSeedOccurrence.seen_at, CollectionSeedOccurrence.id)
    ).all()
    if not occurrences:
        raise ValueError("repair partition has no occurrences")
    latest = occurrences[-1]
    raw = dict(latest.raw_item or {})
    source_platform = str(partition["source_platform"])
    source_item_id = str(partition["source_item_id"])
    raw["source_platform"] = source_platform
    raw["source_item_id"] = source_item_id
    source_url = str(
        raw.get("source_url")
        or raw.get("url")
        or raw.get("itemUrl")
        or latest.source_final_url
        or ""
    ).strip() or None
    title = str(raw.get("title") or raw.get("source_title") or "").strip() or None
    return CollectionSeedItem(
        item_id=str(partition["target_item_id"]),
        source_item_id=source_item_id,
        source_platform=source_platform,
        source_url=source_url,
        title=title,
        status="pending_detail",
        first_seen_job_key=occurrences[0].job_key,
        first_seen_sort_key=occurrences[0].sort_key,
        first_seen_at=occurrences[0].seen_at,
        last_seen_at=occurrences[-1].seen_at,
        source_payload=raw,
        detail_attempt_count=0,
    )


def apply_seed_item_collision_repair(
    session: Session,
    item_id: str,
    *,
    expected_evidence_sha256: str | None = None,
) -> dict[str, Any]:
    report = audit_seed_item_collision(session, item_id)
    if expected_evidence_sha256 and report["evidence_sha256"] != expected_evidence_sha256:
        raise ValueError("collision evidence changed after review")
    if report["decision"] != "auto_split":
        raise ValueError(
            f"seed collision is not eligible for automatic repair: {report['decision']}"
        )

    created_seed_item_ids: list[str] = []
    occurrence_moves: list[dict[str, Any]] = []
    for partition in report["partitions"]:
        target_id = str(partition["target_item_id"])
        if target_id == item_id:
            continue
        if session.get(CollectionSeedItem, target_id) is not None:
            raise ValueError(f"repair target appeared after audit: {target_id}")
        session.add(_partition_seed_row(session, partition))
        created_seed_item_ids.append(target_id)
        session.flush()
        for move in partition["occurrence_moves"]:
            occurrence = session.get(CollectionSeedOccurrence, int(move["occurrence_id"]))
            if occurrence is None or occurrence.item_id != item_id:
                raise ValueError(
                    f"occurrence changed after audit: {move['occurrence_id']}"
                )
            if occurrence.occurrence_key != move["old_occurrence_key"]:
                raise ValueError(
                    f"occurrence key changed after audit: {move['occurrence_id']}"
                )
            occurrence.item_id = target_id
            occurrence.occurrence_key = str(move["new_occurrence_key"])
            occurrence_moves.append(
                {
                    "occurrence_id": occurrence.id,
                    "old_item_id": item_id,
                    "new_item_id": target_id,
                    "old_occurrence_key": str(move["old_occurrence_key"]),
                    "new_occurrence_key": str(move["new_occurrence_key"]),
                }
            )
    session.flush()
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "status": "applied",
        "applied_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
        "old_item_id": item_id,
        "evidence_sha256": report["evidence_sha256"],
        "created_seed_item_ids": created_seed_item_ids,
        "occurrence_moves": occurrence_moves,
    }


def _created_seed_is_rollback_safe(
    session: Session,
    item_id: str,
    receipt_occurrence_ids: set[int],
) -> bool:
    row = session.get(CollectionSeedItem, item_id)
    if row is None:
        return False
    if row.final_json_path or row.selected_json_path or dict(row.source_payload or {}).get(
        "_raw_detail_artifacts"
    ):
        return False
    dependent_count = sum(
        int(session.scalar(statement) or 0)
        for statement in (
            select(func.count()).select_from(CollectionAnalysisRun).where(
                CollectionAnalysisRun.item_id == item_id
            ),
            select(func.count()).select_from(PropertyListing).where(
                PropertyListing.item_id == item_id
            ),
            select(func.count()).select_from(PropertyIngestEvent).where(
                PropertyIngestEvent.item_id == item_id
            ),
        )
    )
    if dependent_count:
        return False
    current_ids = set(
        session.scalars(
            select(CollectionSeedOccurrence.id).where(
                CollectionSeedOccurrence.item_id == item_id
            )
        )
    )
    return current_ids == receipt_occurrence_ids


def rollback_seed_item_collision_repair(
    session: Session,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ValueError("unsupported collision repair receipt")
    if receipt.get("status") != "applied":
        raise ValueError("only an applied collision repair receipt can be rolled back")
    old_item_id = str(receipt.get("old_item_id") or "")
    if not old_item_id or session.get(CollectionSeedItem, old_item_id) is None:
        raise ValueError("collision repair rollback source seed is missing")

    moves = list(receipt.get("occurrence_moves") or [])
    if not moves:
        raise ValueError("collision repair receipt has no occurrence moves")
    created_ids = [str(value) for value in receipt.get("created_seed_item_ids") or []]
    original_state = True
    applied_state = True
    for move in moves:
        occurrence = session.get(CollectionSeedOccurrence, int(move["occurrence_id"]))
        original_state = original_state and occurrence is not None and (
            occurrence.item_id == old_item_id
            and occurrence.occurrence_key == move["old_occurrence_key"]
        )
        applied_state = applied_state and occurrence is not None and (
            occurrence.item_id == str(move["new_item_id"])
            and occurrence.occurrence_key == move["new_occurrence_key"]
        )
    created_rows = [session.get(CollectionSeedItem, item_id) for item_id in created_ids]
    if original_state and not any(created_rows):
        return {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "status": "already_rolled_back",
            "old_item_id": old_item_id,
            "restored_occurrence_count": 0,
            "removed_seed_item_ids": [],
        }
    if not applied_state or any(row is None for row in created_rows):
        raise ValueError("collision repair is neither fully applied nor fully rolled back")

    move_ids_by_target: dict[str, set[int]] = {}
    for move in moves:
        target = str(move["new_item_id"])
        move_ids_by_target.setdefault(target, set()).add(int(move["occurrence_id"]))
        occurrence = session.get(CollectionSeedOccurrence, int(move["occurrence_id"]))
        if (
            occurrence is None
            or occurrence.item_id != target
            or occurrence.occurrence_key != move["new_occurrence_key"]
        ):
            raise ValueError(f"repaired occurrence changed: {move['occurrence_id']}")
        duplicate = session.scalars(
            select(CollectionSeedOccurrence.id).where(
                CollectionSeedOccurrence.occurrence_key == move["old_occurrence_key"],
                CollectionSeedOccurrence.id != occurrence.id,
            )
        ).first()
        if duplicate is not None:
            raise ValueError(f"rollback occurrence key is occupied: {move['occurrence_id']}")

    for target in created_ids:
        if not _created_seed_is_rollback_safe(
            session,
            target,
            move_ids_by_target.get(target, set()),
        ):
            raise ValueError(f"repaired seed has changed and cannot be rolled back: {target}")

    for move in moves:
        occurrence = session.get(CollectionSeedOccurrence, int(move["occurrence_id"]))
        occurrence.item_id = old_item_id
        occurrence.occurrence_key = str(move["old_occurrence_key"])
    session.flush()
    for target_id in created_ids:
        row = session.get(CollectionSeedItem, target_id)
        if row is not None:
            session.delete(row)
    session.flush()
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "rolled_back",
        "rolled_back_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
        "old_item_id": old_item_id,
        "restored_occurrence_count": len(moves),
        "removed_seed_item_ids": created_ids,
    }


__all__ = [
    "RECEIPT_SCHEMA_VERSION",
    "apply_seed_item_collision_repair",
    "rollback_seed_item_collision_repair",
]
