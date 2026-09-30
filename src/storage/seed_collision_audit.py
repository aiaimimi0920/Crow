from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.collection.seed_list_parser import normalize_source_item_id
from src.collection.seed_scan_policy import GenericSeedScanPolicy

from .models import (
    CollectionAnalysisRun,
    CollectionSeedItem,
    CollectionSeedOccurrence,
    CollectionSeedScanJob,
    PropertyIngestEvent,
    PropertyListing,
)


REPORT_SCHEMA_VERSION = "seed_collision_report_v1"
_TAOBAO_PLATFORMS = frozenset({"taobao", "taobao_judicial", "taobao_sf", "sf.taobao.com"})


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def target_item_id(source_platform: str, source_item_id: str) -> str:
    if source_platform.lower() in _TAOBAO_PLATFORMS:
        return source_item_id
    return GenericSeedScanPolicy(source_platform=source_platform).storage_item_id(source_item_id)


def occurrence_key(
    *,
    item_id: str,
    job_key: str,
    sort_key: str,
    page: int,
    rank: int,
) -> str:
    raw = f"{item_id}|{job_key}|{sort_key}|{page}|{rank}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _occurrence_identity(
    occurrence: CollectionSeedOccurrence,
    job: CollectionSeedScanJob | None,
) -> tuple[tuple[str, str] | None, list[str]]:
    raw = occurrence.raw_item if isinstance(occurrence.raw_item, Mapping) else {}
    raw_platform = _text(raw.get("source_platform"))
    job_metadata = job.metadata_json if job and isinstance(job.metadata_json, Mapping) else {}
    job_platform = _text(job_metadata.get("source_platform"))
    raw_source_id = _text(raw.get("source_item_id") or raw.get("id") or raw.get("item_id"))
    issues: list[str] = []
    if not raw_platform:
        issues.append(f"occurrence:{occurrence.id}:missing_source_platform")
    if not raw_source_id:
        issues.append(f"occurrence:{occurrence.id}:missing_source_item_id")
    if raw_platform and job_platform and raw_platform != job_platform:
        issues.append(f"occurrence:{occurrence.id}:job_platform_conflict")
    if issues:
        return None, issues
    return (raw_platform, normalize_source_item_id(raw_source_id)), []


def _has_detail_artifacts(row: CollectionSeedItem) -> bool:
    payload = row.source_payload if isinstance(row.source_payload, Mapping) else {}
    return bool(
        row.final_json_path
        or row.selected_json_path
        or payload.get("_raw_detail_artifacts")
    )


def _downstream_counts(session: Session, item_id: str) -> dict[str, int]:
    return {
        "analysis_runs": int(
            session.scalar(
                select(func.count()).select_from(CollectionAnalysisRun).where(
                    CollectionAnalysisRun.item_id == item_id
                )
            )
            or 0
        ),
        "property_listings": int(
            session.scalar(
                select(func.count()).select_from(PropertyListing).where(
                    PropertyListing.item_id == item_id
                )
            )
            or 0
        ),
        "ingest_events": int(
            session.scalar(
                select(func.count()).select_from(PropertyIngestEvent).where(
                    PropertyIngestEvent.item_id == item_id
                )
            )
            or 0
        ),
    }


def _report_fingerprint(report: Mapping[str, Any]) -> str:
    material = {
        key: value
        for key, value in report.items()
        if key not in {"evidence_sha256"}
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def audit_seed_item_collision(session: Session, item_id: str) -> dict[str, Any]:
    row = session.get(CollectionSeedItem, str(item_id))
    if row is None:
        raise ValueError(f"seed item not found: {item_id}")
    occurrences = session.scalars(
        select(CollectionSeedOccurrence)
        .where(CollectionSeedOccurrence.item_id == row.item_id)
        .order_by(CollectionSeedOccurrence.id)
    ).all()
    job_keys = sorted({occurrence.job_key for occurrence in occurrences})
    jobs = {
        job.job_key: job
        for job in session.scalars(
            select(CollectionSeedScanJob).where(CollectionSeedScanJob.job_key.in_(job_keys))
        ).all()
    } if job_keys else {}

    grouped: dict[tuple[str, str], list[CollectionSeedOccurrence]] = defaultdict(list)
    issues: list[str] = []
    for occurrence in occurrences:
        if occurrence.rank is None:
            issues.append(f"occurrence:{occurrence.id}:missing_rank")
        identity, occurrence_issues = _occurrence_identity(
            occurrence,
            jobs.get(occurrence.job_key),
        )
        issues.extend(occurrence_issues)
        if identity is not None:
            grouped[identity].append(occurrence)

    partitions: list[dict[str, Any]] = []
    for (platform, source_id), members in sorted(grouped.items()):
        target_id = target_item_id(platform, source_id)
        moves = [
            {
                "occurrence_id": occurrence.id,
                "old_occurrence_key": occurrence.occurrence_key,
                "new_occurrence_key": occurrence_key(
                    item_id=target_id,
                    job_key=occurrence.job_key,
                    sort_key=occurrence.sort_key,
                    page=occurrence.page,
                    rank=int(occurrence.rank or 0),
                ),
            }
            for occurrence in members
        ]
        partitions.append(
            {
                "source_platform": platform,
                "source_item_id": source_id,
                "target_item_id": target_id,
                "occurrence_count": len(members),
                "occurrence_moves": moves,
            }
        )

    downstream = _downstream_counts(session, row.item_id)
    decision = "no_collision"
    if len(partitions) > 1:
        decision = "auto_split"
        if issues:
            decision = "manual_review"
        if _has_detail_artifacts(row) or any(downstream.values()):
            issues.append("dependent_detail_or_analysis_data")
            decision = "manual_review"
        original_partitions = [
            partition for partition in partitions if partition["target_item_id"] == row.item_id
        ]
        if len(original_partitions) != 1:
            issues.append("original_item_id_has_no_unique_partition")
            decision = "manual_review"
        else:
            original = original_partitions[0]
            if (
                _text(row.source_platform) != original["source_platform"]
                or normalize_source_item_id(_text(row.source_item_id)) != original["source_item_id"]
            ):
                issues.append("original_seed_identity_does_not_match_partition")
                decision = "manual_review"
        target_ids = [partition["target_item_id"] for partition in partitions]
        if len(set(target_ids)) != len(target_ids):
            issues.append("multiple_partitions_share_target_item_id")
            decision = "manual_review"
        for partition in partitions:
            target_id = partition["target_item_id"]
            if target_id != row.item_id and session.get(CollectionSeedItem, target_id) is not None:
                issues.append(f"target_seed_item_exists:{target_id}")
                decision = "manual_review"
            for move in partition["occurrence_moves"]:
                existing_key = session.scalars(
                    select(CollectionSeedOccurrence.id).where(
                        CollectionSeedOccurrence.occurrence_key == move["new_occurrence_key"],
                        CollectionSeedOccurrence.id != move["occurrence_id"],
                    )
                ).first()
                if existing_key is not None:
                    issues.append(f"target_occurrence_key_exists:{move['occurrence_id']}")
                    decision = "manual_review"
    elif issues and occurrences:
        decision = "manual_review"

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "item_id": row.item_id,
        "seed_identity": {
            "source_platform": row.source_platform,
            "source_item_id": row.source_item_id,
        },
        "decision": decision,
        "issues": sorted(set(issues)),
        "occurrence_count": len(occurrences),
        "partitions": partitions,
        "has_detail_artifacts": _has_detail_artifacts(row),
        "downstream_counts": downstream,
    }
    report["evidence_sha256"] = _report_fingerprint(report)
    return report


def collision_candidate_item_ids(session: Session) -> list[str]:
    return list(
        session.scalars(
            select(CollectionSeedOccurrence.item_id)
            .group_by(CollectionSeedOccurrence.item_id)
            .having(func.count(CollectionSeedOccurrence.id) > 1)
            .order_by(CollectionSeedOccurrence.item_id)
        )
    )


__all__ = [
    "REPORT_SCHEMA_VERSION",
    "audit_seed_item_collision",
    "collision_candidate_item_ids",
    "occurrence_key",
    "target_item_id",
]
