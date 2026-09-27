"""Locked archive record mutations with atomic publication and failure propagation."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, cast

from . import archive_json_io
from .runtime_state import RuntimeState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectionArchiveRecords:
    runtime: Callable[[], RuntimeState]
    exists: Callable[[str | Path], bool]
    load: Callable[[str | Path], object]

    __all__: ClassVar[list[str]] = [
        "update_file_global",
        "update_item_in_json",
        "remove_item_from_json",
    ]

    def update_file_global(
        self, file_path: str | Path, item_id: object, new_data: dict[str, object]
    ) -> None:
        try:
            with self.runtime().file_lock:
                if self.exists(file_path):
                    all_data = cast(list[dict[str, object]], self.load(file_path))
                    updated = False
                    for i, item in enumerate(all_data):
                        if str(item.get("id")) == item_id:
                            all_data[i] = new_data
                            updated = True
                            break
                    if updated:
                        archive_json_io.write_records(file_path, all_data)
        except Exception:
            logger.exception("Global file write failed")
            raise

    def update_item_in_json(
        self, file_path: str | Path, item_id: object, new_data: dict[str, object]
    ) -> None:
        with self.runtime().file_lock:
            data_list = archive_json_io.read_records(file_path)
            updated = False
            for i, item in enumerate(data_list):
                if str(item.get("id")) == item_id:
                    data_list[i] = new_data
                    updated = True
                    break
            if not updated:
                data_list.append(new_data)
            archive_json_io.write_records(file_path, data_list)

    def remove_item_from_json(self, file_path: str | Path, item_id: object) -> None:
        if not file_path or not self.exists(file_path):
            return
        with self.runtime().file_lock:
            try:
                data_list = cast(list[dict[str, object]], self.load(file_path))
                new_list = [
                    item for item in data_list if str(item.get("id")) != item_id
                ]
                if len(new_list) < len(data_list):
                    archive_json_io.write_records(file_path, new_list)
                    logger.info("Removed item=%s from %s", item_id, file_path)
            except Exception:
                logger.exception("Error removing item=%s", item_id)
                raise
