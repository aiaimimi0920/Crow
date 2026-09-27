"""Collection status readers with explicit, late-bound runtime dependencies."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

from . import collection_repository_status, collection_status_payload
from . import collection_statistics as _collection_statistics
from .collection_observer_queries import query_int as _collection_query_int
from .collection_queue_counts import empty_counts as _empty_seed_queue_counts
from .collection_queue_counts import load_counts
from .collection_status_payload import StatisticsSnapshot

if TYPE_CHECKING:
    from .collection_control_state import CollectionPauseSnapshot
    from .storage.repository import PropertyRepository


def _build_info_payload() -> dict[str, str]:
    return {
        "version": str(os.getenv("FAPAI_BUILD_VERSION") or "development"),
        "commit": str(os.getenv("FAPAI_BUILD_COMMIT") or "unknown"),
        "built_at": str(os.getenv("FAPAI_BUILD_TIME") or "unknown"),
        "source_digest": str(os.getenv("FAPAI_SOURCE_DIGEST") or "unknown"),
    }


@dataclass(frozen=True)
class CollectionStatusReaders:
    repository: Callable[[], PropertyRepository]
    env_flag: Callable[[str, bool], bool]
    prefer_db_reads: Callable[[], bool]
    statistics: Callable[
        [PropertyRepository, Callable[[], dict[str, int]]], StatisticsSnapshot
    ]
    seed_counts: Callable[[], dict[str, int]]
    empty_counts: Callable[[], dict[str, int]]
    api_metrics: Callable[[], Mapping[str, object]]
    runtime_snapshot: Callable[[], Mapping[str, object]]
    build_info: Callable[[], Mapping[str, str]]
    runtime_state_label: Callable[[dict[str, object]], str]
    solver_status: Callable[[], Mapping[str, object]]
    auth_recovery: Callable[[], object]
    status: Callable[[], dict[str, object]]
    control: Callable[[], CollectionPauseSnapshot]
    data_root: Callable[[], Path]
    restart: Callable[[], object]
    challenge_metrics: Callable[[Path], object]
    auth_watcher: Callable[[Path], object]

    __all__: ClassVar[tuple[str, ...]] = (
        "_prefer_db_task_reads",
        "_db_pending_task_candidates",
        "_db_counts_snapshot",
        "_db_data_supply_snapshot",
        "_collection_api_lightweight_status_enabled",
        "_load_collection_seed_queue_counts",
        "_collection_runtime_snapshot",
        "_collection_api_lightweight_status_payload",
        "_collection_observer_overview_payload",
    )

    def _prefer_db_task_reads(self) -> bool:
        return cast(
            bool,
            self.repository().enabled
            and self.env_flag("FAPAI_DB_PREFER_RUNTIME_INDEX", True),
        )

    def _db_pending_task_candidates(self, limit: int = 100) -> list[dict[str, object]]:
        return collection_repository_status.pending_candidates(
            self.repository(), prefer_db_reads=self.prefer_db_reads(), limit=limit
        )

    def _db_counts_snapshot(self) -> dict[str, int]:
        return collection_repository_status.counts_snapshot(self.repository())

    def _db_data_supply_snapshot(self, hours: int = 24) -> dict[str, dict[str, int]]:
        return collection_repository_status.data_supply_snapshot(
            self.repository(), hours=hours
        )

    def _collection_api_lightweight_status_enabled(self) -> bool:
        return self.env_flag("FAPAI_COLLECTION_API_LIGHTWEIGHT_STATUS", False)

    def _load_collection_seed_queue_counts(self) -> dict[str, int]:
        return load_counts(self.repository(), defaults=self.empty_counts)

    def _collection_runtime_snapshot(self) -> dict[str, object]:
        return collection_status_payload.build_runtime_snapshot(
            load_solver_status=self.solver_status,
            load_auth_recovery=self.auth_recovery,
        )

    def _collection_api_lightweight_status_payload(self) -> dict[str, object]:
        snapshot = self.statistics(self.repository(), self.seed_counts)
        return collection_status_payload.build_lightweight_status(
            snapshot,
            load_api_metrics=self.api_metrics,
            empty_counts=self.empty_counts,
            load_runtime_snapshot=self.runtime_snapshot,
            load_build_info=self.build_info,
            database_enabled=lambda: self.repository().enabled,
            runtime_state_label=self.runtime_state_label,
        )

    def _collection_observer_overview_payload(self) -> dict[str, object]:
        return collection_status_payload.build_overview_payload(
            load_status=self.status,
            load_control=self.control,
            load_data_root=self.data_root,
            load_restart=self.restart,
            load_challenge_metrics=self.challenge_metrics,
            load_auth_watcher=self.auth_watcher,
        )


__all__ = [
    "_collection_statistics",
    "_collection_query_int",
    "_empty_seed_queue_counts",
    "_build_info_payload",
]
