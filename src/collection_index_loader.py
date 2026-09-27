"""Load the collection index without initializing the server facade."""

from __future__ import annotations

import glob
import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .collection_runtime_index import CollectionRuntimeIndex
from .runtime_json import load_json_file

logger = logging.getLogger(__name__)


class IndexRepository(Protocol):
    enabled: bool

    def iter_flat_items(self) -> list[dict[str, object]]: ...


def load_collection_index(
    active_data_root: str | Path,
    *,
    collection: CollectionRuntimeIndex,
    repository: IndexRepository,
    prefer_db_index: Callable[[], bool],
    db_counts_snapshot: Callable[[], dict[str, int]],
    sync_record: Callable[[dict[str, object]], object],
    data_path: Callable[[object], str],
    now: Callable[[], datetime],
) -> None:
    collection.clear()

    if not os.path.exists(active_data_root):
        os.makedirs(active_data_root)

    logger.info("Loading collection data")

    prefer_db_runtime_index = repository.enabled and prefer_db_index()
    if prefer_db_runtime_index:
        try:
            counts = db_counts_snapshot()
            total_count = counts["db_total_ids"]
            if total_count:
                pending_count = counts["db_pending_ids"]
                logger.info(
                    "DB-first runtime index enabled; pending items will be cached on demand"
                )
                cached_count, _pending_count = collection.counts_snapshot()
                logger.info(
                    "Loaded runtime cache=%s total_db=%s pending_db=%s",
                    cached_count,
                    total_count,
                    pending_count,
                )
                return
            logger.warning(
                "DB-first runtime index requested but repository is empty; falling back to JSON scan"
            )
        except Exception:
            logger.exception("DB-first runtime index failed; falling back to JSON scan")

    # 1. Scan root JSONs (priority config, current files)
    try:
        root_files = glob.glob(os.path.join(active_data_root, "*.json"))
    except Exception:
        logger.exception("Failed to scan collection root JSON files")
        root_files = []

    # 2. Scan Archive JSONs (Recursive)
    try:
        archive_pattern = os.path.join(active_data_root, "archive", "**", "*.json")
        archive_files = glob.glob(archive_pattern, recursive=True)
    except Exception:
        logger.exception("Failed to scan archived collection JSON files")
        archive_files = []

    files = root_files + archive_files

    # Skip non-data json files (config files, progress files, etc.)
    skip_files = [
        "all_locations.json",
        "sniff_queue",
        "sniff_status",
        "sniff_history",
        "sniff_done",
        "manual_priority_locations.json",
        "sniff_progress.json",
        "collected_locations.json",
        "model_config.json",
        "tuning_history.json",
        "seen_ids.json",
    ]
    # Filter by basename to be safe with paths
    files = [
        f for f in files if not any(skip in os.path.basename(f) for skip in skip_files)
    ]

    logger.info("Loading collection data files=%s", len(files))

    for file_path in files:
        try:
            content = load_json_file(file_path)
        except (OSError, UnicodeError, ValueError):
            logger.exception("Failed to load collection data file=%s", file_path)
            continue

        if isinstance(content, list):
            items = content
        elif isinstance(content, dict):
            items = [content]
        else:
            items = []

        for item in items:
            if not isinstance(item, dict):
                logger.warning("Skipping non-object collection item file=%s", file_path)
                continue
            try:
                item_id = str(item.get("id"))
                if not item_id:
                    continue
                sync_record(item)

                collection.set_seen(item_id, {"file_path": file_path, "data": item})
                is_done = (
                    item.get("status") in ["done", "成交", "failure", "failed_timeout"]
                    or item.get("是否成交") is True
                )
                is_processed = item.get("is_processed", False)

                # Queue valid, unprocessed items through the RuntimeState API.
                if is_done and not is_processed:
                    collection.queue_pending(item_id)
            except (AttributeError, KeyError, TypeError, ValueError):
                logger.exception("Failed to process collection item file=%s", file_path)
    if repository.enabled:
        try:
            db_items = repository.iter_flat_items()
            for item in db_items:
                item_id = str(item.get("id") or item.get("item_id"))
                if not item_id:
                    continue
                sync_record(item)
                existing = collection.get_seen(item_id) or {}
                existing_data = dict(existing.get("data", {}))
                existing_data.update(item)
                sync_record(existing_data)
                file_path = existing.get("file_path")
                if not file_path:
                    file_path = data_path(existing_data.get("auction_date") or now())
                collection.set_seen(
                    item_id, {"file_path": file_path, "data": existing_data}
                )
                is_done = (
                    existing_data.get("status")
                    in ["done", "成交", "failure", "failed_timeout"]
                    or existing_data.get("是否成交") is True
                )
                is_processed = existing_data.get("is_processed", False)
                if is_done and not is_processed:
                    collection.queue_pending(item_id)
            logger.info(
                "Hydrated %s items from database into runtime index", len(db_items)
            )
        except Exception:
            logger.exception("Runtime index hydration failed")

    loaded_count, pending_count = collection.counts_snapshot()
    logger.info("Loaded items=%s pending_detail_tasks=%s", loaded_count, pending_count)
