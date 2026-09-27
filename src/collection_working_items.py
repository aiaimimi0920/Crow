"""Live collection cache access and database-backed working-item lookup."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Protocol

from .collection_archive_paths import ArchiveDates
from .collection_runtime_index import CollectionRuntimeIndex
from .runtime_state import RuntimeState

logger = logging.getLogger(__name__)


class WorkingItemRepository(Protocol):
    enabled: bool

    def get_flat_item(self, item_id: str) -> dict[str, object] | None: ...


class WorkingItemHost(Protocol):
    RUNTIME: RuntimeState
    DB_REPOSITORY: WorkingItemRepository
    datetime: ArchiveDates
    _collection_runtime_index: Callable[[], CollectionRuntimeIndex]
    sync_collection_record: Callable[[dict[str, object]], object]
    get_data_path: Callable[[object], str]


@dataclass(frozen=True)
class CollectionWorkingItems:
    host: WorkingItemHost

    __all__: ClassVar[list[str]] = [
        "_collection_runtime_index",
        "_evict_runtime_item",
        "_get_working_item",
    ]

    def _collection_runtime_index(self) -> CollectionRuntimeIndex:
        return self.host.RUNTIME.collection

    def _evict_runtime_item(self, item_id: object) -> None:
        normalized_id = str(item_id)
        collection = self.host._collection_runtime_index()
        collection.remove_seen(normalized_id)
        collection.remove_pending(normalized_id)

    def _get_working_item(
        self, item_id: object, include_processed: bool = False
    ) -> dict[str, object] | None:
        host = self.host
        normalized_id = str(item_id)
        collection = host._collection_runtime_index()
        entry = collection.get_seen(normalized_id)
        if entry:
            return {
                "data": entry["data"],
                "file_path": entry["file_path"],
                "cached": True,
            }
        if host.DB_REPOSITORY.enabled:
            try:
                item = host.DB_REPOSITORY.get_flat_item(normalized_id)
            except Exception as error:
                logger.error(
                    "Working item fetch failed item=%s error_type=%s",
                    normalized_id,
                    type(error).__name__,
                )
                return None
            if not item:
                return None
            host.sync_collection_record(item)
            if item.get("is_processed") and not include_processed:
                return None
            return {
                "data": item,
                "file_path": host.get_data_path(
                    item.get("auction_date") or host.datetime.datetime.now()
                ),
                "cached": False,
            }
        return None
