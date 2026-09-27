"""Dependencies grouped by the detail operation's three effect owners."""

from collections.abc import Callable
from dataclasses import dataclass

from .contracts import DetailExtractor, Record


@dataclass(frozen=True)
class DetailStorage:
    get_working_item: Callable[[str, bool], Record | None]
    update_item_in_json: Callable[[str, str, Record], None]
    remove_item_from_json: Callable[[str, str], None]
    persist_item_to_db: Callable[[Record, str, Record | None], None]
    mark_item_deleted_in_db: Callable[[str, str, Record | None], None]


@dataclass(frozen=True)
class DetailRuntime:
    evict_runtime_item: Callable[[str], None]
    prefer_db_task_reads: Callable[[], bool]
    queue_pending: Callable[[str], object]
    set_seen: Callable[[str, Record], None]
    remove_pending: Callable[[str], object]

    def completed(self, item_id: str, path: str, record: Record) -> None:
        if self.prefer_db_task_reads():
            self.evict_runtime_item(item_id)
        else:
            self.set_seen(item_id, {"file_path": path, "data": record})
            self.remove_pending(item_id)


@dataclass(frozen=True)
class DetailModels:
    extractor: DetailExtractor
    extract_risk: Callable[..., Record | None]
    sync_risk: Callable[[Record], object]
    report: Callable[..., None]
