"""Locked archive record mutations with atomic publication and failure propagation."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

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
        self,
        file_path: str | Path,
        item_id: object,
        new_data: dict[str, object],
        *,
        merge: bool = False,
    ) -> None:
        """在全局 file_lock 内对分区归档做 upsert（修复无锁读改写）。

        1) 记录/文件缺失时不再静默丢弃，改为追加：原实现只有
           `if self.exists(...)` 分支会写，归档被删过之后所有更新无声消失；
        2) merge=True 时对已存在记录只补空字段，供粗采集新记录分支复用，
           避免整文件 read-modify-write 绕过 file_lock 与加锁写者互相覆盖。
        """
        try:
            with self.runtime().file_lock:
                if self.exists(file_path):
                    all_data = archive_json_io.read_records(file_path)
                else:
                    all_data = []

                index = None
                for pos, item in enumerate(all_data):
                    if str(item.get("id")) == str(item_id):
                        index = pos
                        break

                if index is None:
                    target = new_data
                elif merge:
                    target = all_data[index]
                    for key, value in new_data.items():
                        if value not in (None, "") and target.get(key) in (None, ""):
                            target[key] = value
                else:
                    target = new_data

                if index is None:
                    all_data.append(target)
                else:
                    all_data[index] = target
                archive_json_io.write_records(file_path, all_data)
        except Exception:
            logger.exception("Global file write failed")
            raise

    def update_item_in_json(
        self, file_path: str | Path, item_id: object, new_data: dict[str, object]
    ) -> None:
        with self.runtime().file_lock:
            data_list = archive_json_io.read_records(file_path)
            for index, item in enumerate(data_list):
                if str(item.get("id")) == str(item_id):
                    data_list[index] = new_data
                    break
            else:
                data_list.append(new_data)
            archive_json_io.write_records(file_path, data_list)

    def remove_item_from_json(self, file_path: str | Path, item_id: object) -> None:
        if not file_path:
            return
        with self.runtime().file_lock:
            try:
                if not self.exists(file_path):
                    return
                data_list = archive_json_io.read_records(file_path)
                retained = [
                    item for item in data_list if str(item.get("id")) != str(item_id)
                ]
                if len(retained) != len(data_list):
                    archive_json_io.write_records(file_path, retained)
                    logger.info("Removed item=%s from archive %s", item_id, file_path)
            except Exception:
                logger.exception("Error removing item=%s from archive", item_id)
                raise
