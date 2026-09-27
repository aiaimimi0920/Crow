"""Database status reads with explicit repository ownership."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from src.storage.repository import PropertyRepository

logger = logging.getLogger(__name__)


def pending_candidates(
    repository: PropertyRepository, *, prefer_db_reads: bool, limit: int = 100
) -> list[dict[str, object]]:
    if not prefer_db_reads:
        return []
    try:
        return cast(
            list[dict[str, object]], repository.iter_pending_task_items(limit=limit)
        )
    except Exception:
        logger.exception("[DB] Pending task query failed")
    return []


def counts_snapshot(repository: PropertyRepository) -> dict[str, int]:
    if not repository.enabled:
        return {
            "db_total_ids": 0,
            "db_processed_ids": 0,
            "db_pending_ids": 0,
            "db_detail_captured_ids": 0,
        }
    try:
        return cast(dict[str, int], repository.counts_snapshot())
    except Exception:  # noqa: BLE001 - retain legacy aggregate-query fallback.
        return {
            "db_total_ids": repository.count_listings(),
            "db_processed_ids": repository.count_processed_listings(),
            "db_pending_ids": repository.count_pending_task_items(),
            "db_detail_captured_ids": repository.count_detail_captured_items(),
        }


def data_supply_snapshot(
    repository: PropertyRepository, *, hours: int = 24
) -> dict[str, dict[str, int]]:
    if not repository.enabled or not hasattr(repository, "event_type_counts"):
        return {
            "detail_archive_fetch_recent": {},
            "maintenance_writeback_recent": {},
            "stage_transition_recent": {},
        }
    fetch_counts = repository.event_type_counts(
        (
            "detail_archive_fetched",
            "detail_archive_fetch_blocked",
            "detail_archive_fetch_failed",
        ),
        hours=hours,
    )
    maintenance_counts = repository.event_type_counts(
        (
            "detail_replay_prepared",
            "recent_coordinate_backfill",
            "archived_detail_backfill",
        ),
        hours=hours,
    )
    stage_transition_counts = repository.event_type_counts(
        (
            "seed_stage_transition",
            "detail_stage_transition",
            "analysis_stage_transition",
            "analysis_ready_transition",
        ),
        hours=hours,
    )
    return {
        "detail_archive_fetch_recent": fetch_counts,
        "maintenance_writeback_recent": maintenance_counts,
        "stage_transition_recent": stage_transition_counts,
    }
