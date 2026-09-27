"""Read-only collection status HTTP adapter with live host dependencies."""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Protocol, cast

from .collection_repository_status import collection_stage_snapshot

Record = dict[str, object]


class StatusHandler(Protocol):
    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: Record
    ) -> None: ...


class StatusIndex(Protocol):
    def state_snapshot(
        self,
    ) -> tuple[dict[str, Record], tuple[str, ...], Record]: ...


class StatusRepository(Protocol):
    enabled: bool

    def stage_status_counts(self) -> dict[str, int]: ...
    def search_task_counts(self) -> dict[str, int]: ...


class StatusMetrics(Protocol):
    def get_api_metrics(self) -> Record: ...


class StatusSeeds(Protocol):
    def counts_snapshot(self) -> dict[str, int]: ...


class CollectionStatusHost(Protocol):
    DATA_DIR: str | Path
    DISPATCH_COOLDOWN_SECONDS: int
    DB_REPOSITORY: StatusRepository
    llm_helper: StatusMetrics

    def _collection_runtime_index(self) -> StatusIndex: ...
    def _collection_api_lightweight_status_enabled(self) -> bool: ...
    def _collection_api_lightweight_status_payload(self) -> Record: ...
    def _prefer_db_task_reads(self) -> bool: ...
    def _db_counts_snapshot(self) -> dict[str, int]: ...
    def _db_pending_task_candidates(self, *, limit: int) -> list[dict[str, str]]: ...
    def _utc_now(self) -> datetime: ...
    def _as_utc_timestamp(self, value: object) -> datetime | None: ...
    def _seed_collection_service(self) -> StatusSeeds: ...
    def _collection_runtime_snapshot(self) -> Record: ...
    def _db_data_supply_snapshot(self, hours: int) -> Record: ...


@dataclass(frozen=True)
class CollectionStatusHandler:
    _get_status: Callable[[StatusHandler, object, str, dict[str, list[str]]], None]
    __all__: ClassVar[list[str]] = ["_get_status"]


def bind_collection_status(host: CollectionStatusHost) -> CollectionStatusHandler:
    def _get_status(
        handler: StatusHandler,
        parsed: object,
        request_path: str,
        query: dict[str, list[str]],
    ) -> None:
        runtime_index = host._collection_runtime_index()
        try:
            if host._collection_api_lightweight_status_enabled():
                handler.send_json(host._collection_api_lightweight_status_payload())
                return
            db_total_ids = None
            db_processed_ids = None
            db_pending_ids = None
            db_detail_captured_ids = None
            next_batch: list[str]
            if host._prefer_db_task_reads():
                counts = host._db_counts_snapshot()
                total_ids = counts["db_total_ids"]
                ai_finalized_count = counts["db_processed_ids"]
                detail_captured_count = counts["db_detail_captured_ids"]
                captured_count = max(ai_finalized_count, detail_captured_count)
                db_total_ids = total_ids
                db_processed_ids = ai_finalized_count
                db_pending_ids = counts["db_pending_ids"]
                db_detail_captured_ids = detail_captured_count
                next_batch = []
                now = host._utc_now()
                _, _, dispatched_tasks = runtime_index.state_snapshot()
                for candidate in host._db_pending_task_candidates(limit=100):
                    if len(next_batch) >= 10:
                        break
                    tid = candidate["id"]
                    last_time = host._as_utc_timestamp(dispatched_tasks.get(tid))
                    if (
                        not last_time
                        or (now - last_time).total_seconds()
                        >= host.DISPATCH_COOLDOWN_SECONDS
                    ):
                        next_batch.append(tid)
            else:
                seen_ids, pending_tasks, dispatched_tasks = (
                    runtime_index.state_snapshot()
                )
                total_ids = len(seen_ids)
                captured_ids = {
                    tid
                    for tid, entry in seen_ids.items()
                    if cast(Record, entry.get("data", {})).get("is_processed")
                }
                ai_finalized_count = len(captured_ids)
                for filename in os.listdir(host.DATA_DIR):
                    if filename.startswith("item-") and (
                        filename.endswith((".txt", ".html"))
                    ):
                        match = re.search(r"item-(\d+)", filename)
                        if match:
                            captured_ids.add(match.group(1))
                captured_count = len(captured_ids)
                next_batch = []
                now = host._utc_now()
                for tid in pending_tasks[:100]:
                    if len(next_batch) >= 10:
                        break
                    last_time = host._as_utc_timestamp(dispatched_tasks.get(tid))
                    if (
                        not last_time
                        or (now - last_time).total_seconds()
                        >= host.DISPATCH_COOLDOWN_SECONDS
                    ):
                        next_batch.append(tid)
            if host._prefer_db_task_reads():
                pass
            if host.DB_REPOSITORY.enabled:
                search_counts = host._seed_collection_service().counts_snapshot()
                status_info = {
                    "pending_locations": search_counts.get("search_pending", 0),
                    "done_locations": search_counts.get("search_done", 0),
                }
            else:
                legacy_counts = host._seed_collection_service().counts_snapshot()
                status_info = {
                    "pending_locations": legacy_counts.get("search_pending", 0),
                    "done_locations": legacy_counts.get("search_done", 0),
                }
            api_metrics = host.llm_helper.get_api_metrics()
            stage_snapshot = collection_stage_snapshot(host.DB_REPOSITORY)
            runtime_snapshot = host._collection_runtime_snapshot()
            handler.send_json(
                {
                    "paused": runtime_snapshot["paused"],
                    "total_ids": total_ids,
                    "captured_count": captured_count,
                    "ai_finalized_count": ai_finalized_count,
                    "db_mode": host._prefer_db_task_reads(),
                    "db_total_ids": db_total_ids,
                    "db_processed_ids": db_processed_ids,
                    "db_pending_ids": db_pending_ids,
                    "db_detail_captured_ids": db_detail_captured_ids,
                    "sniff_queue_count": status_info.get("pending_locations", 0),
                    "sniff_done_count": status_info.get("done_locations", 0),
                    "next_batch_preview": next_batch,
                    "api_success_rate": api_metrics.get("success_rate", 0.0),
                    "api_avg_response_time_ms": api_metrics.get(
                        "avg_response_time_ms", 0.0
                    ),
                    "api_total_calls": api_metrics.get("total_calls", 0),
                    "api_success_calls": api_metrics.get("success_calls", 0),
                    "captcha_solver": runtime_snapshot["captcha_solver"],
                    "auth_recovery": runtime_snapshot["auth_recovery"],
                    "collection_scopes": runtime_snapshot["collection_scopes"],
                    "data_supply_recent_24h": host._db_data_supply_snapshot(24)
                    if host.DB_REPOSITORY.enabled
                    else {},
                    "collection_stage": stage_snapshot,
                }
            )
        except Exception as error:  # noqa: BLE001 - preserve status HTTP boundary
            handler.send_error_json(
                status=500,
                code="COLLECTION_STATUS_FAILED",
                message="状态概览生成失败",
                details={"error": str(error)},
            )

    return CollectionStatusHandler(_get_status)
