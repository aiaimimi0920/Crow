"""Native collection write callbacks with a live repository dependency."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol, cast

logger = logging.getLogger(__name__)


class CollectionWriteRepository(Protocol):
    def upsert_flat_item(
        self,
        item: dict[str, object],
        event_type: str,
        event_payload: dict[str, object] | None = None,
    ) -> None: ...

    def mark_deleted(
        self,
        item_id: str,
        reason: str,
        event_payload: dict[str, object] | None = None,
    ) -> None: ...


class CollectionWriteHost(Protocol):
    DB_REPOSITORY: CollectionWriteRepository


@dataclass(frozen=True)
class CollectionDatabaseWrites:
    repository: Callable[[], CollectionWriteRepository]

    __all__: ClassVar[list[str]] = ["persist_item_to_db", "mark_item_deleted_in_db"]

    def persist_item_to_db(
        self,
        item: dict[str, object],
        event_type: str,
        event_payload: dict[str, object] | None = None,
    ) -> None:
        try:
            self.repository().upsert_flat_item(
                item, event_type=event_type, event_payload=event_payload
            )
        except Exception as error:
            logger.error(
                "Database upsert failed item=%s error_type=%s",
                item.get("id")
                or cast(Mapping[str, object], item.get("source", {})).get("item_id"),
                type(error).__name__,
            )
            raise

    def mark_item_deleted_in_db(
        self,
        item_id: object,
        reason: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        try:
            self.repository().mark_deleted(
                str(item_id), reason=reason, event_payload=payload
            )
        except Exception as error:
            logger.error(
                "Database mark_deleted failed item=%s error_type=%s",
                item_id,
                type(error).__name__,
            )
            raise


def bind_collection_database_writes(
    host: CollectionWriteHost,
) -> CollectionDatabaseWrites:
    return CollectionDatabaseWrites(repository=lambda: host.DB_REPOSITORY)
