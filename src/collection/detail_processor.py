from __future__ import annotations

import datetime
import json
import logging
import os
import re
import time
import uuid
from contextlib import AbstractContextManager
from pathlib import Path

from src.archive_json_io import write_text as write_archive_text
from src.detail_artifacts import extract_detail_artifacts, get_detail_archive_path

from .contracts import CollectionAdapter, Record
from .detail_execution import DetailModels, DetailRuntime, DetailStorage
from .detail_failures import DetailFailures, InputVersion, input_version, read_capture

logger = logging.getLogger(__name__)


class DetailProcessor:
    """Processes one captured page while delegating product rules to an adapter."""

    def __init__(
        self,
        *,
        data_root: Path,
        retry_dir: Path,
        adapter: CollectionAdapter,
        capture_lock: AbstractContextManager[object],
    ) -> None:
        self.data_root = data_root
        self.failures = DetailFailures(data_root)
        self.retry_dir = retry_dir
        self.adapter = adapter
        self.capture_lock = capture_lock

    @staticmethod
    def _parse_ai_record(raw: str, item_id: str) -> Record:
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
        record: Record,
        content: str,
        item_id: str,
        file_path: str,
        revision: str,
    ) -> None:
        archive_path = get_detail_archive_path(
            self.data_root,
            self.adapter.archive_date(record),
            item_id,
            extension=".html" if Path(file_path).suffix == ".html" else ".raw.txt",
            revision=revision,
        )
        write_archive_text(archive_path, content)
        record["detail_archive_path"] = os.path.relpath(
            archive_path, self.data_root
        ).replace("\\", "/")

    def _schedule_retry(
        self,
        *,
        item_id: str,
        runtime: DetailRuntime,
    ) -> bool:
        retry_path = self.retry_dir / f"item-{item_id}.html.retry"
        if retry_path.exists():
            logger.warning("Detail field retry exhausted item=%s", item_id)
            retry_path.unlink(missing_ok=True)
            return False

        logger.warning("Scheduling detail field retry item=%s", item_id)
        write_archive_text(
            retry_path,
            f"Retry scheduled at {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        )
        if not runtime.prefer_db_task_reads():
            runtime.queue_pending(item_id)
        return True

    def _cleanup_success(
        self, *, file_path: str, item_id: str, version: InputVersion
    ) -> None:
        try:
            with self.capture_lock:
                if input_version(Path(file_path)) != version:
                    return
                Path(file_path).unlink(missing_ok=True)
                self.failures.clear(item_id)
                (self.retry_dir / f"item-{item_id}.html.retry").unlink(missing_ok=True)
        except OSError:
            logger.warning("Detail cleanup deferred item=%s", item_id)
            return
        html_name = f"item-{item_id}.html"
        for path in (
            self.data_root / "html" / f"{html_name}.processing",
            self.data_root / f"{html_name}.processing",
        ):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Detail processing marker cleanup deferred item=%s", item_id
                )

    @staticmethod
    def _report(models: DetailModels, **event: object) -> None:
        try:
            models.report(task_type="analyze_html", **event)
        except Exception:  # noqa: BLE001 - telemetry must not control publication.
            logger.warning("Detail telemetry unavailable item=%s", event.get("item_id"))

    def process(
        self,
        file_path: str,
        *,
        storage: DetailStorage,
        runtime: DetailRuntime,
        models: DetailModels,
    ) -> None:
        filename = os.path.basename(file_path)
        match = re.search(r"item-(.+?)(?:\.html|\.txt|$)", filename)
        if not match:
            logger.warning("Skipping detail file without item ID: %s", filename)
            return

        item_id = match.group(1)
        started_at: float | None = None
        version: InputVersion | None = None
        stage = "capture"
        try:
            if not os.path.exists(file_path):
                logger.warning(
                    "Detail file disappeared before processing: %s", filename
                )
                return
            content, version = read_capture(Path(file_path))
            if not content.strip():
                raise ValueError("Captured detail is empty")

            stage = "lookup"
            original_record = storage.get_working_item(item_id, True)
            if original_record is None:
                raise LookupError("Collection seed is unavailable")
            logger.info("Processing detail item=%s", item_id)
            started_at = time.time()
            stage = "extraction"
            raw = models.extractor.extract(content, item_id=item_id)
            if not raw:
                raise ValueError("Empty response from AI")
            stage = "model_result"
            record = self._parse_ai_record(raw, item_id)
            logger.info("AI detail extraction succeeded item=%s", item_id)

            if getattr(self.adapter, "collects_avm_risk", False):
                stage = "risk_facts"
                risk_features = models.extract_risk(content, item_id=item_id)
                if risk_features:
                    record["avm_risk_features"] = risk_features
                    models.sync_risk(record)
                    logger.info("Attached source risk facts item=%s", item_id)
                else:
                    logger.warning("No additional source risk facts item=%s", item_id)

            stage = "validation"
            existing = original_record.get("data", {})
            self.adapter.prepare_detail_record(
                record, existing=existing, item_id=item_id
            )
            target_json_path = original_record["file_path"]
            stage = "archive"
            # A failed refresh must never replace evidence referenced by a prior commit.
            revision = uuid.uuid4().hex
            self._archive_source(
                record=record,
                content=content,
                item_id=item_id,
                file_path=file_path,
                revision=revision,
            )
            stage = "artifacts"
            artifacts = extract_detail_artifacts(
                self.data_root,
                content,
                item_id=item_id,
                auction_date=self.adapter.archive_date(record),
                source_url=self.adapter.source_url(record),
                archive_revision=revision,
            )
            record.update(
                {
                    key: value
                    for key, value in artifacts.items()
                    if value not in (None, "", [])
                }
            )

            stage = "validation"
            if not self.adapter.accepts_detail(record):
                logger.warning(
                    "AI rejected item=%s; removing it from collection storage", item_id
                )
                stage = "json"
                storage.remove_item_from_json(target_json_path, item_id)
                stage = "database"
                storage.mark_item_deleted_in_db(
                    item_id,
                    "detail_not_done",
                    {"item_id": item_id, "target_json_path": target_json_path},
                )
                stage = "runtime"
                runtime.evict_runtime_item(item_id)
            else:
                retry_reason = self.adapter.retry_reason(record)
                if retry_reason and self._schedule_retry(
                    item_id=item_id,
                    runtime=runtime,
                ):
                    return
                self.adapter.finalize_detail_record(record)
                stage = "json"
                storage.update_item_in_json(target_json_path, item_id, record)
                stage = "database"
                storage.persist_item_to_db(
                    record,
                    "detail_enriched",
                    {
                        "item_id": item_id,
                        "file_path": file_path,
                        "source_file": file_path,
                    },
                )
                stage = "runtime"
                runtime.completed(item_id, target_json_path, record)
                logger.info("Detail saved item=%s path=%s", item_id, target_json_path)
                recall_count = record.get("recall_count", record.get("召回数"))
                confidence = record.get("final_confidence")
                if confidence is None:
                    confidence = (
                        record.get("置信度")
                        or record.get("最终置信度")
                        or record.get("extraction_confidence")
                    )
                self._report(
                    models,
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
                version=version,
            )
        except Exception as error:  # noqa: BLE001 - retain evidence for every failed stage.
            code = "COLLECTION_DETAIL_" + stage.upper() + "_FAILED"
            logger.error(
                "Detail failed item=%s stage=%s error_type=%s",
                item_id,
                stage,
                type(error).__name__,
            )
            duration_ms = (
                (time.time() - started_at) * 1000 if started_at is not None else None
            )
            self._report(
                models,
                item_id=item_id,
                duration_ms=duration_ms,
                recall_count=0,
                final_confidence=None,
                success=False,
                failure_reason=code,
            )
            try:
                self.failures.record(item_id, version, stage, error)
            except OSError:
                logger.error(
                    "Could not record detail failure item=%s stage=%s", item_id, stage
                )
