from __future__ import annotations

import datetime
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict

from src.archive_json_io import write_text as write_archive_text
from src.detail_artifacts import extract_detail_artifacts, get_detail_archive_path

from .contracts import CollectionAdapter, DetailExtractor

logger = logging.getLogger(__name__)


class DetailProcessor:
    """Processes one captured page while delegating product rules to an adapter."""

    def __init__(
        self,
        *,
        data_root: Path,
        failed_dir: Path,
        retry_dir: Path,
        adapter: CollectionAdapter,
    ) -> None:
        self.data_root = data_root
        self.failed_dir = failed_dir
        self.retry_dir = retry_dir
        self.adapter = adapter

    @staticmethod
    def _parse_ai_record(raw: str, item_id: str) -> Dict[str, Any]:
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
        record = json.loads(raw)
        if not isinstance(record, dict):
            raise ValueError("AI did not return a dictionary")
        record["id"] = int(item_id) if item_id.isdigit() else item_id
        record["source_item_id"] = item_id
        return record

    def _archive_source(
        self,
        *,
        record: Dict[str, Any],
        content: str,
        item_id: str,
        file_path: str,
    ) -> None:
        try:
            archive_path = get_detail_archive_path(
                self.data_root,
                self.adapter.archive_date(record),
                item_id,
                extension=os.path.splitext(file_path)[1] or ".html",
            )
            write_archive_text(archive_path, content)
            record["detail_archive_path"] = os.path.relpath(
                archive_path, self.data_root
            ).replace("\\", "/")
        except Exception as error:
            logger.exception("Detail archive failed for item=%s", item_id)
            raise

        try:
            artifacts = extract_detail_artifacts(
                self.data_root,
                content,
                item_id=item_id,
                auction_date=self.adapter.archive_date(record),
                source_url=self.adapter.source_url(record),
            )
            for key, value in artifacts.items():
                if value not in (None, "", []):
                    record.setdefault(key, value)
        except Exception as error:
            logger.exception("Detail artifact extraction failed for item=%s", item_id)

    def _schedule_retry(
        self,
        *,
        item_id: str,
        reason: str,
        file_path: str,
        prefer_db_task_reads: Callable[[], bool],
        queue_pending: Callable[[str], bool],
    ) -> bool:
        retry_path = self.retry_dir / f"item-{item_id}.html.retry"
        if retry_path.exists():
            logger.warning("Detail retry exhausted for item=%s: %s", item_id, reason)
            retry_path.unlink(missing_ok=True)
            return False

        logger.warning("Scheduling detail retry for item=%s: %s", item_id, reason)
        retry_path.write_text(
            f"Retry scheduled at {datetime.datetime.now(datetime.timezone.utc).isoformat()}: {reason}",
            encoding="utf-8",
        )
        if not prefer_db_task_reads():
            queue_pending(item_id)
        try:
            os.remove(file_path)
            (self.data_root / "html" / f"item-{item_id}.html").unlink(missing_ok=True)
        except Exception:
            pass
        return True

    def _save_completed(
        self,
        *,
        record: Dict[str, Any],
        target_json_path: str,
        item_id: str,
        file_path: str,
        update_item_in_json: Callable[[str, str, Dict[str, Any]], None],
        persist_item_to_db: Callable[[Dict[str, Any], str, Dict[str, Any] | None], None],
        evict_runtime_item: Callable[[str], None],
        prefer_db_task_reads: Callable[[], bool],
        set_seen: Callable[[str, Dict[str, Any]], None],
        remove_pending: Callable[[str], None],
    ) -> None:
        self.adapter.finalize_detail_record(record)
        update_item_in_json(target_json_path, item_id, record)
        persist_item_to_db(
            record,
            "detail_enriched",
            {"item_id": item_id, "file_path": file_path, "source_file": file_path},
        )
        if prefer_db_task_reads():
            evict_runtime_item(item_id)
        else:
            entry = {"file_path": target_json_path, "data": record}
            set_seen(item_id, entry)
            remove_pending(item_id)
        logger.info("Detail saved item=%s path=%s quality=%s", item_id, target_json_path, self.adapter.quality_summary(record))

    def _cleanup_success(self, *, file_path: str, item_id: str, failed_marker_path: Path) -> None:
        try:
            os.remove(file_path)
        except Exception:
            pass
        failed_marker_path.unlink(missing_ok=True)
        html_name = f"item-{item_id}.html"
        for path in (
            self.data_root / "html" / f"{html_name}.processing",
            self.data_root / f"{html_name}.processing",
        ):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    def process(
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
        detail_extractor: DetailExtractor,
        extract_avm_risk_features: Callable[[str, str | None], Dict[str, Any]],
        log_prediction_event: Callable[..., None],
        queue_pending: Callable[[str], bool],
        set_seen: Callable[[str, Dict[str, Any]], None],
        remove_pending: Callable[[str], None],
    ) -> None:
        filename = os.path.basename(file_path)
        match = re.search(r"item-(.+?)(?:\.html|\.txt|$)", filename)
        if not match:
            logger.warning("Skipping detail file without item ID: %s", filename)
            try:
                os.remove(file_path)
            except Exception:
                pass
            return

        item_id = match.group(1)
        failed_marker_path = self.failed_dir / f"item-{item_id}.html.failed"
        started_at: float | None = None
        publication_started = False
        try:
            failed_once = failed_marker_path.exists()
            if not os.path.exists(file_path):
                logger.warning("Detail file disappeared before processing: %s", filename)
                return
            content = Path(file_path).read_text(encoding="utf-8")
            if not content.strip():
                logger.warning("Empty detail content for item=%s; deleting", item_id)
                try:
                    Path(file_path).unlink(missing_ok=True)
                except Exception:
                    pass
                if failed_once:
                    failed_marker_path.unlink(missing_ok=True)
                return

            logger.info("Processing detail item=%s", item_id)
            started_at = time.time()
            raw = detail_extractor.extract(content, item_id=item_id)
            if raw:
                logger.info("AI detail extraction succeeded item=%s preview=%s", item_id, raw[:200])
            if not raw:
                raise ValueError("Empty response from AI")
            record = self._parse_ai_record(raw, item_id)

            if getattr(self.adapter, "collects_avm_risk", False):
                risk_features = extract_avm_risk_features(content, item_id=item_id)
                if risk_features:
                    record["avm_risk_features"] = risk_features
                    sync_avm_risk_aliases(record)
                    logger.info("Attached AVM risk features item=%s", item_id)
                else:
                    logger.warning("AVM risk extraction failed item=%s; skipped attachment", item_id)

            original_record = get_working_item(item_id, include_processed=True)
            existing = original_record.get("data", {}) if original_record else {}
            self.adapter.prepare_detail_record(record, existing=existing, item_id=item_id)
            target_json_path = (
                original_record["file_path"]
                if original_record
                else get_data_path(self.adapter.partition_key(record))
            )
            publication_started = True
            self._archive_source(record=record, content=content, item_id=item_id, file_path=file_path)

            if not self.adapter.accepts_detail(record):
                logger.warning("AI rejected item=%s; removing it from collection storage", item_id)
                remove_item_from_json(target_json_path, item_id)
                mark_item_deleted_in_db(
                    item_id,
                    "detail_not_done",
                    {"item_id": item_id, "target_json_path": target_json_path},
                )
                evict_runtime_item(item_id)
            else:
                retry_reason = self.adapter.retry_reason(record)
                if retry_reason and self._schedule_retry(
                    item_id=item_id,
                    reason=retry_reason,
                    file_path=file_path,
                    prefer_db_task_reads=prefer_db_task_reads,
                    queue_pending=queue_pending,
                ):
                    return
                self._save_completed(
                    record=record,
                    target_json_path=target_json_path,
                    item_id=item_id,
                    file_path=file_path,
                    update_item_in_json=update_item_in_json,
                    persist_item_to_db=persist_item_to_db,
                    evict_runtime_item=evict_runtime_item,
                    prefer_db_task_reads=prefer_db_task_reads,
                    set_seen=set_seen,
                    remove_pending=remove_pending,
                )
                recall_count = record.get("recall_count", record.get("召回数"))
                confidence = record.get("final_confidence")
                if confidence is None:
                    confidence = record.get("置信度") or record.get("最终置信度") or record.get("extraction_confidence")
                log_prediction_event(
                    task_type="analyze_html",
                    item_id=item_id,
                    duration_ms=(time.time() - started_at) * 1000,
                    recall_count=recall_count,
                    final_confidence=confidence,
                    success=True,
                    failure_reason=None,
                )
            self._cleanup_success(
                file_path=file_path,
                item_id=item_id,
                failed_marker_path=failed_marker_path,
            )
        except Exception as error:
            logger.exception("Error processing detail item=%s", item_id)
            duration_ms = (
                (time.time() - started_at) * 1000 if started_at is not None else None
            )
            log_prediction_event(
                task_type="analyze_html",
                item_id=item_id,
                duration_ms=duration_ms,
                recall_count=0,
                final_confidence=None,
                success=False,
                failure_reason=str(error),
            )
            if publication_started:
                logger.error(
                    "Detail publication failed item=%s; retaining captured input",
                    item_id,
                )
                if not failed_marker_path.exists():
                    try:
                        failed_marker_path.write_text(str(error), encoding="utf-8")
                    except OSError:
                        logger.exception(
                            "Could not record detail publication failure item=%s",
                            item_id,
                        )
                return
            if failed_marker_path.exists():
                logger.error(
                    "Second detail failure item=%s; deleting file to avoid deadlock",
                    item_id,
                )
                try:
                    Path(file_path).unlink(missing_ok=True)
                except Exception:
                    pass
                failed_marker_path.unlink(missing_ok=True)
            else:
                logger.warning(
                    "First detail failure item=%s; marking as failed", item_id
                )
                failed_marker_path.write_text(str(error), encoding="utf-8")
