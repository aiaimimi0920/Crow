"""Live service construction and serialized seed intake for the server facade."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

from .collection_runtime_index import CollectionRuntimeIndex
from .collection_working_items import WorkingItemRepository

if TYPE_CHECKING:
    from .collection.contracts import CollectionAdapter
    from .collection.detail_service import DetailCollectionService as DetailService
    from .collection.seed_service import SeedCollectionService as SeedService


class AdapterResolver(Protocol):
    def __call__(self, *, default: str) -> CollectionAdapter: ...


class CollectionServiceHost(Protocol):
    DB_REPOSITORY: WorkingItemRepository
    DATA_DIR: str
    JOBS_DIR: str
    SeedCollectionService: type[SeedService]
    DetailCollectionService: type[DetailService]
    collection_adapter_from_env: AdapterResolver
    _collection_runtime_index: Callable[[], CollectionRuntimeIndex]
    _seed_collection_service: Callable[[], SeedService]
    parse_price: Callable[[object], float | None]
    _safe_int: Callable[[object], int | None]
    _prefer_db_task_reads: Callable[[], bool]
    get_data_path: Callable[[object], str]
    update_file_global: Callable[[str, str, dict[str, object]], None]
    persist_item_to_db: Callable[
        [dict[str, object], str, dict[str, object] | None], None
    ]
    _evict_runtime_item: Callable[[str], None]
    archive_list_payload: Callable[..., str | None]


@dataclass(frozen=True)
class CollectionServiceOperations:
    host: CollectionServiceHost

    __all__: ClassVar[list[str]] = [
        "_seed_collection_service",
        "_detail_collection_service",
        "build_sniff_stub",
        "handle_seed_batch_submission",
    ]

    def _seed_collection_service(self) -> SeedService:
        host = self.host
        return host.SeedCollectionService(
            repository=host.DB_REPOSITORY,
            jobs_dir=host.JOBS_DIR,
            data_root=host.DATA_DIR,
            adapter=host.collection_adapter_from_env(default="taobao_judicial"),
        )

    def _detail_collection_service(
        self, data_root: str | Path | None = None
    ) -> DetailService:
        host = self.host
        return host.DetailCollectionService(
            data_root=data_root or host.DATA_DIR,
            repository=host.DB_REPOSITORY,
            adapter=host.collection_adapter_from_env(default="taobao_judicial"),
            dispatch_lock=host._collection_runtime_index().lock,
        )

    def build_sniff_stub(self, item: dict[str, object]) -> dict[str, object]:
        host = self.host
        return cast(
            "dict[str, object]",
            host._seed_collection_service().build_seed_stub(
                item, parse_price=host.parse_price, safe_int=host._safe_int
            ),
        )

    def handle_seed_batch_submission(
        self, data: dict[str, object]
    ) -> dict[str, object]:
        host = self.host
        collection = host._collection_runtime_index()
        with collection.lock:
            return cast(
                "dict[str, object]",
                host._seed_collection_service().submit_batch(
                    data,
                    parse_price=host.parse_price,
                    safe_int=host._safe_int,
                    prefer_db_task_reads=host._prefer_db_task_reads,
                    get_seen_entry=getattr(
                        collection,
                        "get_seen",
                        lambda item_id: collection.seen_ids.get(item_id),
                    ),
                    get_flat_item=lambda item_id: (
                        host.DB_REPOSITORY.get_flat_item(item_id)
                        if host.DB_REPOSITORY.enabled
                        else None
                    ),
                    get_data_path=host.get_data_path,
                    update_file_global=host.update_file_global,
                    persist_item_to_db=host.persist_item_to_db,
                    evict_runtime_item=host._evict_runtime_item,
                    archive_list_payload=host.archive_list_payload,
                    set_seen=collection.set_seen,
                    queue_pending=collection.queue_pending,
                ),
            )
