from __future__ import annotations

import datetime
import json
import logging
import tempfile
import threading
import time
from copy import deepcopy
from datetime import timezone as _timezone
from pathlib import Path
from typing import Any, Callable, ContextManager, Dict

from .adapters.generic_product import GenericProductAdapter
from .adapters.taobao_judicial import TaobaoJudicialAuctionAdapter
from .contracts import CollectionAdapter, DetailExtractor
from .detail_extractors import resolve_detail_extractor
from .detail_processor import DetailProcessor


# The dispatch map is shared by HTTP worker threads.  Keep the cooldown check
# and timestamp update atomic even when repository iteration performs I/O.
_DISPATCH_LOCK = threading.RLock()
logger = logging.getLogger(__name__)


def _utc_now() -> datetime.datetime:
    try:
        return datetime.datetime.now(_timezone.utc)
    except TypeError:
        # Keep deterministic zero-argument clock fakes without tagging local time as UTC.
        try:
            utcnow = datetime.datetime.utcnow
        except AttributeError:
            utcnow = None
        if callable(utcnow):
            try:
                return utcnow().replace(tzinfo=_timezone.utc)
            except TypeError:
                pass
        return datetime.datetime.now().replace(tzinfo=_timezone.utc)


def _as_utc(value: datetime.datetime) -> datetime.datetime:
    return value.replace(tzinfo=_timezone.utc) if value.tzinfo is None else value.astimezone(_timezone.utc)


class DetailCollectionService:
    """Thin orchestration wrapper for detail-stage automation entrypoints."""

    @staticmethod
    def _preserve_seed_values(
        record: Dict[str, Any],
        seed: Dict[str, Any],
        adapter: CollectionAdapter | None = None,
    ) -> None:
        """Preserve seed values while keeping the legacy Taobao default."""

        active_adapter = adapter or TaobaoJudicialAuctionAdapter()
        preserve = getattr(active_adapter, "preserve_seed_values", None)
        if preserve is None:
            for key, value in seed.items():
                if value not in (None, "", []) and record.get(key) in (None, "", []):
                    record[key] = value
            return
        preserve(record, seed)

    def __init__(
        self,
        data_root: str | Path,
        repository: Any = None,
        adapter: CollectionAdapter | None = None,
        dispatch_lock: ContextManager[object] | None = None,
    ):
        self.data_root = Path(data_root)
        self.repository = repository
        self.adapter = adapter or GenericProductAdapter()
        self._dispatch_lock = dispatch_lock or _DISPATCH_LOCK

    @property
    def failed_dir(self) -> Path:
        path = self.data_root / "failed"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def retry_dir(self) -> Path:
        path = self.data_root / "retry"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _expire_dispatches(
        dispatched_tasks: Dict[str, datetime.datetime], now: datetime.datetime, cooldown_seconds: int,
    ) -> None:
        # Only transient dispatch timestamps expire; archived records stay intact.
        expired = [
            item_id for item_id, dispatched_at in dispatched_tasks.items()
            if (now - (dispatched_at.replace(tzinfo=_timezone.utc) if dispatched_at.tzinfo is None else dispatched_at)).total_seconds() >= cooldown_seconds
        ]
        for item_id in expired:
            dispatched_tasks.pop(item_id, None)

    def next_task(
        self,
        dispatched_tasks: Dict[str, datetime.datetime],
        cooldown_seconds: int,
        dispatch_lock: ContextManager[object] | None = None,
        mark_dispatched: Callable[[str, datetime.datetime], None] | None = None,
        get_dispatched: Callable[[str], datetime.datetime | None] | None = None,
        prune_dispatched: Callable[[datetime.datetime, int], None] | None = None,
    ) -> Dict[str, Any]:
        now = _utc_now()
        lock = dispatch_lock or self._dispatch_lock
        with lock:
            if prune_dispatched is not None:
                prune_dispatched(now, cooldown_seconds)
            else:
                self._expire_dispatches(dispatched_tasks, now, cooldown_seconds)
        if self.repository and getattr(self.repository, "enabled", False):
            for candidate in self.repository.iter_pending_task_items(limit=100):
                tid = str(candidate["id"])
                with lock:
                    last_time = get_dispatched(tid) if get_dispatched is not None else dispatched_tasks.get(tid)
                    if last_time and (now - _as_utc(last_time)).total_seconds() < cooldown_seconds:
                        continue
                    timestamp = now.replace(tzinfo=None) if last_time and last_time.tzinfo is None else now
                    if mark_dispatched is not None:
                        mark_dispatched(tid, timestamp)
                    else:
                        dispatched_tasks[tid] = timestamp
                    return {"url": candidate.get("url")}
        return {}

    def next_visit_task(
        self,
        *,
        dispatched_tasks: Dict[str, datetime.datetime],
        cooldown_seconds: int,
        legacy_entries: list[tuple[str, Dict[str, Any]]] | None = None,
        dispatch_lock: ContextManager[object] | None = None,
        mark_dispatched: Callable[[str, datetime.datetime], None] | None = None,
        get_dispatched: Callable[[str], datetime.datetime | None] | None = None,
        prune_dispatched: Callable[[datetime.datetime, int], None] | None = None,
    ) -> Dict[str, Any]:
        now = _utc_now()
        lock = dispatch_lock or self._dispatch_lock
        with lock:
            if prune_dispatched is not None:
                prune_dispatched(now, cooldown_seconds)
            else:
                self._expire_dispatches(dispatched_tasks, now, cooldown_seconds)
        candidate_entries: list[tuple[str, Dict[str, Any]]] = []
        if self.repository and getattr(self.repository, "enabled", False):
            candidate_entries = [
                (str(item.get("id")), {"data": {"url": item.get("url"), "is_processed": item.get("is_processed", False)}})
                for item in self.repository.iter_pending_flat_items(limit=500)
            ]
        elif legacy_entries is not None:
            candidate_entries = legacy_entries

        for item_id, entry in candidate_entries:
            data = entry.get("data", {})
            if not data.get("url") or data.get("is_processed"):
                continue
            html_name = f"item-{item_id}.html"
            html_path = self.data_root / "html" / html_name
            retry_path = self.retry_dir / f"{html_name}.retry"
            legacy_html = self.data_root / html_name
            txt_path = self.data_root / f"item-{item_id}.txt"
            p_html = self.data_root / "html" / f"{html_name}.processing"
            p_legacy = self.data_root / f"{html_name}.processing"
            exists = any(path.exists() for path in (html_path, retry_path, legacy_html, txt_path, p_html, p_legacy))
            if exists:
                continue
            with lock:
                last_time = get_dispatched(item_id) if get_dispatched is not None else dispatched_tasks.get(item_id)
                if last_time and (now - _as_utc(last_time)).total_seconds() < cooldown_seconds:
                    continue
                timestamp = now.replace(tzinfo=None) if last_time and last_time.tzinfo is None else now
                if mark_dispatched is not None:
                    mark_dispatched(item_id, timestamp)
                else:
                    dispatched_tasks[item_id] = timestamp
                return {
                    "task_type": "visit",
                    "id": item_id,
                    "url": data.get("url"),
                }
        return {"task_type": "none"}

    def batch_tasks(
        self,
        *,
        dispatched_tasks: Dict[str, datetime.datetime],
        cooldown_seconds: int,
        batch_size: int = 300,
        mark_dispatched: Callable[[str, datetime.datetime], None] | None = None,
        get_dispatched: Callable[[str], datetime.datetime | None] | None = None,
        prune_dispatched: Callable[[datetime.datetime, int], None] | None = None,
    ) -> Dict[str, Any]:
        now = _utc_now()
        with self._dispatch_lock:
            if prune_dispatched is not None:
                prune_dispatched(now, cooldown_seconds)
            else:
                self._expire_dispatches(dispatched_tasks, now, cooldown_seconds)
        if self.repository and getattr(self.repository, "enabled", False):
            counts = self.repository.counts_snapshot()
            total_count = counts["db_total_ids"]
            pending_candidates = self.repository.iter_pending_task_items(limit=batch_size * 3)
            pending_count = counts["db_pending_ids"]
            done_count = max(0, total_count - pending_count)
            tasks = []
            for candidate in pending_candidates:
                tid = str(candidate["id"])
                with self._dispatch_lock:
                    last_time = get_dispatched(tid) if get_dispatched is not None else dispatched_tasks.get(tid)
                    if last_time and (now - _as_utc(last_time)).total_seconds() < cooldown_seconds:
                        continue
                    tasks.append({"id": tid, "url": candidate.get("url")})
                    timestamp = now.replace(tzinfo=None) if last_time and last_time.tzinfo is None else now
                    if mark_dispatched is not None:
                        mark_dispatched(tid, timestamp)
                    else:
                        dispatched_tasks[tid] = timestamp
                    if len(tasks) >= batch_size:
                        break
            return {"tasks": tasks, "total": total_count, "done": done_count, "pending": pending_count}
        return {"tasks": [], "total": 0, "done": 0, "pending": 0}

    def submit_html(
        self,
        *,
        item_id: str,
        html_content: str,
        status: str | None,
        get_working_item: Callable[[str, bool], Dict[str, Any] | None],
        apply_flat_override_patch: Callable[[Dict[str, Any], Dict[str, Any]], None],
        reset_structured_sections_for_resync: Callable[[Dict[str, Any]], None],
        update_file_global: Callable[[str, str, Dict[str, Any]], None],
        persist_item_to_db: Callable[
            [Dict[str, Any], str, Dict[str, Any] | None], None
        ],
        evict_runtime_item: Callable[[str], None],
        submit_task: Callable[[str], None],
        prefer_db_task_reads: Callable[[], bool],
        remove_pending: Callable[[str], bool | None],
    ) -> Dict[str, Any]:
        working_item = get_working_item(item_id, True)
        if not working_item:
            return {"status": "id_not_found"}

        html_dir = self.data_root / "html"
        html_dir.mkdir(parents=True, exist_ok=True)
        html_path = html_dir / f"item-{item_id}.html"
        # Unconfirmed status submissions must not be visible to the HTML scanner.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=html_dir,
            prefix=".pending-",
            suffix=".tmp",
            delete=False,
        ) as staged:
            staged.write(html_content)
            staged_path = Path(staged.name)

        if status:
            working_data = deepcopy(working_item["data"])
            working_data["status"] = status
            apply_flat_override_patch(working_data, {"status": status})
            reset_structured_sections_for_resync(working_data)
            self.adapter.sync_record(working_data)
            update_file_global(working_item["file_path"], item_id, working_data)
            event_type = "analyze_html_status"
            persist_item_to_db(
                working_data,
                event_type,
                {
                    "item_id": item_id,
                    "status": status,
                    "source_file": working_item["file_path"],
                },
            )
            normalized_status = str(status).strip().lower()
            working_item["data"].clear()
            working_item["data"].update(working_data)
            with self._dispatch_lock:
                if working_item["cached"]:
                    remove_pending(item_id)
            if normalized_status.startswith("failed_") and prefer_db_task_reads():
                evict_runtime_item(item_id)

        staged_path.replace(html_path)
        logger.info("Saved HTML to %s", html_path)
        if status and str(status).strip().lower().startswith("failed_"):
            return {"status": "queued"}

        submit_task(str(html_path))
        return {"status": "queued"}

    def apply_working_item_patch(
        self,
        *,
        item_id: str,
        patch_data: Dict[str, Any],
        event_type: str,
        get_working_item: Callable[[str, bool], Dict[str, Any] | None],
        apply_flat_override_patch: Callable[[Dict[str, Any], Dict[str, Any]], None],
        reset_structured_sections_for_resync: Callable[[Dict[str, Any]], None],
        update_file_global: Callable[[str, str, Dict[str, Any]], None],
        persist_item_to_db: Callable[
            [Dict[str, Any], str, Dict[str, Any] | None], None
        ],
        evict_runtime_item: Callable[[str], None],
        prefer_db_task_reads: Callable[[], bool],
        remove_pending: Callable[[str], bool | None],
        mark_processed: bool = False,
        force_status: str | None = None,
    ) -> Dict[str, Any]:
        working_item = get_working_item(item_id, include_processed=True)
        if not (item_id and working_item):
            return {"status": "id_not_found"}

        current_data = deepcopy(working_item["data"])
        current_data.update(patch_data)
        if mark_processed:
            current_data["is_processed"] = True
        if force_status is not None:
            current_data["status"] = force_status
        apply_flat_override_patch(current_data, patch_data)
        if force_status is not None:
            apply_flat_override_patch(current_data, {"status": force_status})
        reset_structured_sections_for_resync(current_data)
        self.adapter.sync_record(current_data)

        file_path = working_item["file_path"]
        update_file_global(file_path, item_id, current_data)
        persist_item_to_db(
            current_data, event_type, {"item_id": item_id, "source_file": file_path}
        )
        working_item["data"].clear()
        working_item["data"].update(current_data)

        with self._dispatch_lock:
            if working_item["cached"]:
                remove_pending(item_id)

        if prefer_db_task_reads():
            evict_runtime_item(item_id)
        return {"status": "ok"}

    def infer_location(
        self,
        *,
        address: str,
        title: str,
        item_id: str | None,
        chat_with_glm: Callable[[str], str],
        log_prediction_event: Callable[..., None],
    ) -> Dict[str, Any]:
        prompt = self.adapter.location_prompt(address=address, title=title)
        if prompt is None:
            log_prediction_event(
                task_type="infer_location",
                item_id=item_id,
                duration_ms=0,
                recall_count=0,
                final_confidence=None,
                success=False,
                failure_reason="location inference is not supported by this collection adapter",
            )
            return {}
        infer_started_at = time.time()
        try:
            resp = chat_with_glm(prompt)
            if "```json" in resp:
                resp = resp.split("```json")[1].split("```")[0]
            elif "```" in resp:
                resp = resp.split("```")[1].split("```")[0]
            result = json.loads(resp.strip())
            log_prediction_event(
                task_type="infer_location",
                item_id=item_id,
                duration_ms=(time.time() - infer_started_at) * 1000,
                recall_count=None,
                final_confidence=None,
                success=True,
                failure_reason=None,
            )
            return result
        except Exception as e:
            logger.exception("Error calling LLM for location inference")
            log_prediction_event(
                task_type="infer_location",
                item_id=item_id,
                duration_ms=(time.time() - infer_started_at) * 1000,
                recall_count=0,
                final_confidence=None,
                success=False,
                failure_reason=str(e),
            )
            return {}

    def process_html_file(
        self,
        file_path: str,
        *,
        get_working_item: Callable[[str, bool], Dict[str, Any] | None],
        get_data_path: Callable[[Any], str],
        update_item_in_json: Callable[[str, str, Dict[str, Any]], None],
        remove_item_from_json: Callable[[str, str], None],
        persist_item_to_db: Callable[[Dict[str, Any], str, Dict[str, Any] | None], None],
        mark_item_deleted_in_db: Callable[[str, str, Dict[str, Any] | None], None],
        evict_runtime_item: Callable[[str], None],
        prefer_db_task_reads: Callable[[], bool],
        sync_avm_risk_aliases: Callable[[Dict[str, Any]], Dict[str, Any]],
        extract_avm_risk_features: Callable[[str, str | None], Dict[str, Any]],
        log_prediction_event: Callable[..., None],
        queue_pending: Callable[[str], bool],
        set_seen: Callable[[str, Dict[str, Any]], None],
        remove_pending: Callable[[str], None],
        detail_extractor: DetailExtractor | None = None,
        extract_auction_data: Callable[..., str] | None = None,
    ) -> None:
        resolved_detail_extractor = resolve_detail_extractor(
            detail_extractor=detail_extractor,
            legacy_extract_auction_data=extract_auction_data,
        )
        DetailProcessor(
            data_root=self.data_root,
            failed_dir=self.failed_dir,
            retry_dir=self.retry_dir,
            adapter=self.adapter,
        ).process(
            file_path,
            get_working_item=get_working_item,
            get_data_path=get_data_path,
            update_item_in_json=update_item_in_json,
            remove_item_from_json=remove_item_from_json,
            persist_item_to_db=persist_item_to_db,
            mark_item_deleted_in_db=mark_item_deleted_in_db,
            evict_runtime_item=evict_runtime_item,
            prefer_db_task_reads=prefer_db_task_reads,
            sync_avm_risk_aliases=sync_avm_risk_aliases,
            detail_extractor=resolved_detail_extractor,
            extract_avm_risk_features=extract_avm_risk_features,
            log_prediction_event=log_prediction_event,
            queue_pending=queue_pending,
            set_seen=set_seen,
            remove_pending=remove_pending,
        )

    def fetch_missing_archives(
        self,
        *,
        limit: int = 20,
        timeout: int = 15,
        extract_risk: bool = False,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        from src.collection.detail_archive_fetch import fetch_missing_detail_archives

        return fetch_missing_detail_archives(
            data_root=self.data_root,
            limit=limit,
            timeout=timeout,
            extract_risk=extract_risk,
            dry_run=dry_run,
        )

    def backfill_archived(
        self,
        *,
        limit: int = 200,
        dry_run: bool = True,
        extract_risk: bool = False,
    ) -> Dict[str, Any]:
        from tools.backfill_archived_details import backfill_archived_details

        return backfill_archived_details(
            self.data_root,
            limit=limit,
            dry_run=dry_run,
            extract_risk=extract_risk,
        )

    def prepare_replay(
        self,
        *,
        window_days: int = 7,
        limit: int = 100,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        from tools.prepare_recent_detail_replay import prepare_recent_detail_replay

        return prepare_recent_detail_replay(
            self.data_root,
            window_days=window_days,
            limit=limit,
            dry_run=dry_run,
        )

    def run_maintenance(
        self,
        *,
        window_days: int = 7,
        archive_limit: int = 200,
        sample_limit: int = 20,
        replay_limit: int = 100,
        fetch_limit: int = 20,
        fetch_timeout: int = 15,
        reconcile_limit: int = 200,
        dry_run: bool = True,
        extract_risk: bool = False,
        prepare_replay: bool = False,
        fetch_archives: bool = False,
    ) -> Dict[str, Any]:
        from tools.run_recent_enrich_maintenance import run_recent_enrich_maintenance

        return run_recent_enrich_maintenance(
            data_root=self.data_root,
            window_days=window_days,
            archive_limit=archive_limit,
            sample_limit=sample_limit,
            replay_limit=replay_limit,
            fetch_limit=fetch_limit,
            fetch_timeout=fetch_timeout,
            reconcile_limit=reconcile_limit,
            dry_run=dry_run,
            extract_risk=extract_risk,
            prepare_replay=prepare_replay,
            fetch_archives=fetch_archives,
        )
