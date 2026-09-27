from __future__ import annotations

import datetime
import logging
from copy import deepcopy
from typing import Any, Callable, Dict

from src.archive_json_io import read_records, write_records

from .adapters.generic_product import GenericProductAdapter
from .contracts import CollectionAdapter
from .search_bootstrap import (
    DEFAULT_CATEGORIES,
    DEFAULT_SORT_ORDER,
    iter_job_snapshots,
    load_all_location_codes,
    load_priority_codes,
)

logger = logging.getLogger(__name__)


class SeedCollectionService:
    """Orchestrate source-neutral seed intake and task assignment."""

    def __init__(
        self,
        repository: Any = None,
        jobs_dir: str | None = None,
        data_root: str | None = None,
        adapter: CollectionAdapter | None = None,
    ):
        self.repository = repository
        self.jobs_dir = jobs_dir
        self.data_root = data_root
        self.adapter = adapter or GenericProductAdapter()

    def build_seed_stub(
        self,
        item: Dict[str, Any],
        parse_price: Callable[[Any], Any],
        safe_int: Callable[[Any], Any],
    ) -> Dict[str, Any]:
        return self.adapter.build_seed_record(
            item,
            parse_number=parse_price,
            safe_int=safe_int,
        )

    def register_search_task(
        self,
        task: Dict[str, Any],
        *,
        leased_by: str | None = None,
        lease_seconds: int = 90,
    ) -> bool:
        """Register one source-specific rough-collection task."""
        if not (self.repository and getattr(self.repository, "enabled", False)):
            return False
        return bool(
            self.repository.bootstrap_search_task(
                task,
                leased_by=leased_by,
                lease_seconds=lease_seconds,
                policy=self.adapter.search_task_policy,
            )
        )

    def _bootstrap_db_search_tasks(self) -> None:
        if not getattr(self.adapter, "bootstraps_legacy_search_tasks", False):
            return
        if not (self.repository and getattr(self.repository, "enabled", False)):
            return
        if getattr(self.repository, "count_search_tasks", None) and self.repository.count_search_tasks() > 0:
            return

        snapshots = iter_job_snapshots(self.jobs_dir) if self.jobs_dir else []
        all_codes = load_all_location_codes(self.data_root) if self.data_root else []
        if snapshots:
            self.repository.import_search_task_snapshots(snapshots)

        if all_codes:
            self.repository.ensure_seed_search_tasks(all_codes, DEFAULT_CATEGORIES, sort_param="2")

    def next_task(self, session_id: str, *, paused: bool = False) -> Dict[str, Any]:
        if paused:
            return {"task": None, "message": "Paused (Captcha)"}
        if not (self.repository and getattr(self.repository, "enabled", False)):
            return {"task": None, "message": "搜索任务数据库未启用"}

        try:
            self._bootstrap_db_search_tasks()
            priority_codes = load_priority_codes(self.jobs_dir) if self.jobs_dir else []
            task = self.repository.claim_search_task(
                session_id,
                priority_codes=priority_codes,
                sort_order=DEFAULT_SORT_ORDER,
                policy=self.adapter.search_task_policy,
            )
        except Exception:
            logging.getLogger(__name__).exception("Seed task assignment failed")
            raise

        if task:
            task.setdefault("session_id", session_id)
            return {
                "task": task,
                "location": {"code": task.get("location_code"), "name": task.get("location_code")},
                "is_resume": task.get("is_resume", False),
                "message": task.get("desc", "Task assigned"),
            }
        return {"task": None, "message": "所有嗅探任务已完成"}

    def report_progress(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = payload.get("url")
        task_key = payload.get("task_key")
        session_id = payload.get("session_id")
        if not url and not task_key:
            raise ValueError("Missing URL or task_key")
        policy = self.adapter.search_task_policy
        if policy.requires_lease_owner and not task_key:
            raise ValueError("Source-scoped search progress requires task_key")
        if policy.requires_lease_owner and not session_id:
            raise ValueError("Source-scoped search progress requires session_id")

        if self.repository and getattr(self.repository, "enabled", False):
            self.repository.report_search_task_progress(
                url=url,
                page_num=int(payload.get("page_num", 1) or 1),
                has_next=bool(payload.get("has_next", True)),
                max_page=int(payload.get("total_pages")) if payload.get("total_pages") else None,
                zero_bid_detected=bool(payload.get("zero_bid_detected", False)),
                task_key=str(task_key) if task_key else None,
                next_url=str(payload.get("next_url")) if payload.get("next_url") else None,
                session_id=str(session_id) if session_id else None,
                policy=policy,
            )

        return {"status": "ok"}

    def counts_snapshot(self) -> Dict[str, int]:
        if self.repository and getattr(self.repository, "enabled", False):
            try:
                return self.repository.search_task_counts()
            except Exception:
                logging.getLogger(__name__).exception("Seed task counts failed")
                raise
        return {
            "search_pending": 0,
            "search_in_progress": 0,
            "search_done": 0,
            "search_pruned": 0,
        }

    def submit_batch(
        self,
        data: Dict[str, Any],
        *,
        parse_price: Callable[[Any], Any],
        safe_int: Callable[[Any], Any],
        prefer_db_task_reads: Callable[[], bool],
        get_seen_entry: Callable[[str], Any],
        get_flat_item: Callable[[str], Dict[str, Any] | None],
        get_data_path: Callable[[Any], str],
        update_file_global: Callable[[str, str, Dict[str, Any]], None],
        persist_item_to_db: Callable[[Dict[str, Any], str, Dict[str, Any] | None], None],
        evict_runtime_item: Callable[[str], None],
        archive_list_payload: Callable[[Any, datetime.datetime], str | None],
        set_seen: Callable[[str, Dict[str, Any]], None],
        queue_pending: Callable[[str], bool],
    ) -> Dict[str, Any]:
        items = data.get("items", [])
        source_page_url = data.get("source_page_url") or data.get("page_url") or data.get("url")
        list_payload_path = None
        try:
            list_payload_path = archive_list_payload(
                data.get("raw_payload"), datetime.datetime.now(datetime.timezone.utc)
            )
        except Exception as archive_error:
            logger.exception("List payload archive failed")

        new_count = 0
        staged_new: Dict[str, Dict[str, Any]] = {}
        items_by_path: Dict[str, list[tuple[str, Dict[str, Any], Dict[str, Any]]]] = {}

        for item in items:
            item_id = self.adapter.item_id(item)
            status = str(item.get("status", "")).lower()
            if list_payload_path and not item.get("list_payload_path"):
                item["list_payload_path"] = list_payload_path
            if source_page_url and not item.get("source_page_url"):
                item["source_page_url"] = source_page_url

            prepared_item = self.adapter.build_seed_record(
                item,
                parse_number=parse_price,
                safe_int=safe_int,
            )
            if source_page_url and not prepared_item.get("source_page_url"):
                prepared_item["source_page_url"] = source_page_url

            if not self.adapter.accepts_seed(item, prepared_item):
                continue

            if item_id in staged_new:
                staged_record = staged_new[item_id]["data"]
                for key, value in prepared_item.items():
                    if value not in (None, "") and staged_record.get(key) in (None, ""):
                        staged_record[key] = value
                self.adapter.sync_record(staged_record)
                continue

            existing_entry = get_seen_entry(item_id)
            db_existing_item = None
            if existing_entry is None:
                try:
                    db_existing_item = get_flat_item(item_id)
                except Exception:
                    logger.exception("Existing item lookup failed item=%s", item_id)
                    raise

            event_payload = {
                "source": "collection_seed_batch",
                "item_id": item_id,
                "source_page_url": source_page_url,
            }

            if existing_entry or db_existing_item:
                logger.info(
                    "Seed item existing title=%s id=%s",
                    item.get("title", "Unknown"),
                    item_id,
                )
                merged = deepcopy(
                    (existing_entry or {}).get("data", {}) or db_existing_item or {}
                )
                for key, value in prepared_item.items():
                    if value not in (None, "") and merged.get(key) in (None, ""):
                        merged[key] = value
                self.adapter.sync_record(merged)
                target_file_path = (
                    existing_entry["file_path"]
                    if existing_entry and not prefer_db_task_reads()
                    else get_data_path(self.adapter.partition_key(merged))
                )
                update_file_global(target_file_path, item_id, merged)
                event_payload["source_file"] = target_file_path
                persist_item_to_db(merged, "sniff_saved", event_payload)
                if existing_entry and not prefer_db_task_reads():
                    entry = {**existing_entry, "data": merged}
                    if set_seen is not None:
                        set_seen(item_id, entry)
                    else:
                        existing_entry["data"] = merged
                    if not merged.get("is_processed"):
                        queue_pending(item_id)
                if prefer_db_task_reads():
                    evict_runtime_item(item_id)
                continue

            logger.info(
                "Seed item new title=%s status=%s url=%s",
                item.get("title", "Unknown"),
                status,
                item.get("url"),
            )
            if get_seen_entry(item_id) is None:
                a_date = self.adapter.partition_key(prepared_item)
                file_path = get_data_path(a_date)
                entry = {
                    "file_path": file_path,
                    "data": prepared_item,
                    "status": item.get("status"),
                }
                staged_new[item_id] = entry
                event_payload["source_file"] = file_path
                items_by_path.setdefault(file_path, []).append(
                    (item_id, entry, event_payload)
                )

        for file_path, entries in items_by_path.items():
            current_file_data = read_records(file_path)
            archived_by_id = {
                str(record.get("id")): record for record in current_file_data
            }
            for item_id, entry, _ in entries:
                archived = archived_by_id.get(item_id)
                if archived is None:
                    current_file_data.append(entry["data"])
                else:
                    for key, value in entry["data"].items():
                        if value not in (None, "") and archived.get(key) in (None, ""):
                            archived[key] = value
                    self.adapter.sync_record(archived)
                    entry["data"] = archived
            write_records(file_path, current_file_data)
            for item_id, entry, event_payload in entries:
                prepared_item = entry["data"]
                persist_item_to_db(prepared_item, "sniff_saved", event_payload)
                if not prefer_db_task_reads():
                    set_seen(item_id, entry)
                    if not prepared_item.get("is_processed"):
                        queue_pending(item_id)
                if prefer_db_task_reads():
                    evict_runtime_item(item_id)
                new_count += 1

        return {"status": "ok", "new": new_count}
