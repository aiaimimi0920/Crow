from __future__ import annotations

import json
import os
from typing import Any, Dict

from sqlalchemy import func, select

from .models import (
    CollectionSeedItem,
    CollectionSeedOccurrence,
    CollectionSeedScanJob,
    CollectionSeedScanProgress,
)
from .repository_context import _resolve_collection_artifact_path, _utc_now


class RepositoryObserverItemsMixin:
    def collection_observer_items(
        self,
        *,
        stage: str = "links",
        limit: int = 100,
        offset: int = 0,
        location_code: str | None = None,
    ) -> Dict[str, Any]:
        normalized_stage = (stage or "links").strip().lower()
        if normalized_stage not in {"links", "details", "analysis"}:
            normalized_stage = "links"
        safe_limit = max(1, min(int(limit or 100), 500))
        safe_offset = max(0, int(offset or 0))
        safe_location_code = str(location_code or "").strip()
        if not self.enabled:
            return {
                "stage": normalized_stage,
                "limit": safe_limit,
                "offset": safe_offset,
                "location_code": safe_location_code or None,
                "total": 0,
                "items": [],
            }
        self.initialize()
        clauses = self._collection_observer_stage_clauses(normalized_stage)
        with self.session_factory() as session:
            total_stmt = select(func.count()).select_from(CollectionSeedItem)
            list_stmt = select(CollectionSeedItem)
            for clause in clauses:
                total_stmt = total_stmt.where(clause)
                list_stmt = list_stmt.where(clause)
            if safe_location_code:
                region_item_ids = (
                    select(CollectionSeedOccurrence.item_id)
                    .join(CollectionSeedScanJob, CollectionSeedOccurrence.job_key == CollectionSeedScanJob.job_key)
                    .where(
                        CollectionSeedScanJob.location_code == safe_location_code,
                        CollectionSeedScanJob.status != "archived",
                    )
                    .distinct()
                )
                total_stmt = total_stmt.where(CollectionSeedItem.item_id.in_(region_item_ids))
                list_stmt = list_stmt.where(CollectionSeedItem.item_id.in_(region_item_ids))
            total = int(session.scalar(total_stmt) or 0)
            rows = session.scalars(
                list_stmt.order_by(
                    CollectionSeedItem.last_seen_at.desc(),
                    CollectionSeedItem.first_seen_at.desc(),
                    CollectionSeedItem.item_id.asc(),
                )
                .offset(safe_offset)
                .limit(safe_limit)
            ).all()
            occurrences = self._latest_seed_occurrence_payloads(session, [row.item_id for row in rows])
            return {
                "stage": normalized_stage,
                "limit": safe_limit,
                "offset": safe_offset,
                "location_code": safe_location_code or None,
                "total": total,
                "items": [self._seed_item_observer_payload(session, row, occurrences) for row in rows],
            }

    @staticmethod
    def _read_collection_artifact(path_value: str | None, *, max_chars: int) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "path": path_value,
            "resolved_path": None,
            "exists": False,
            "content": None,
            "truncated": False,
            "json": None,
            "error": None,
        }
        if not path_value:
            return payload
        try:
            resolved_path = _resolve_collection_artifact_path(path_value)
            payload["resolved_path"] = resolved_path
            if not resolved_path or not os.path.isfile(resolved_path):
                return payload
            payload["exists"] = True
            with open(resolved_path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read(max_chars + 1)
            if len(content) > max_chars:
                payload["content"] = content[:max_chars]
                payload["truncated"] = True
            else:
                payload["content"] = content
            if str(path_value).lower().endswith(".json") and payload["content"] is not None and not payload["truncated"]:
                try:
                    payload["json"] = json.loads(str(payload["content"]))
                except json.JSONDecodeError as exc:
                    payload["error"] = f"json_decode_error: {exc}"
        except OSError as exc:
            payload["error"] = str(exc)
        return payload

    def collection_observer_item_detail(self, item_id: str, *, max_chars: int = 100_000) -> Dict[str, Any]:
        safe_item_id = str(item_id or "").strip()
        safe_max_chars = max(1, min(int(max_chars or 100_000), 1_000_000))
        if not self.enabled or not safe_item_id:
            return {"found": False, "item_id": safe_item_id, "item": None, "occurrences": [], "artifacts": {}}
        self.initialize()
        with self.session_factory() as session:
            row = session.get(CollectionSeedItem, safe_item_id)
            if row is None:
                return {"found": False, "item_id": safe_item_id, "item": None, "occurrences": [], "artifacts": {}}
            item_payload = self._seed_item_observer_payload(session, row)
            occurrences = [
                {
                    "id": occurrence.id,
                    "job_key": occurrence.job_key,
                    "progress_key": occurrence.progress_key,
                    "sort_key": occurrence.sort_key,
                    "sort_name": occurrence.sort_name,
                    "st_param": occurrence.st_param,
                    "page": occurrence.page,
                    "rank": occurrence.rank,
                    "source_page_url": occurrence.source_page_url,
                    "source_final_url": occurrence.source_final_url,
                    "raw_item": dict(occurrence.raw_item or {}),
                    "seen_at": self._fmt_dt(occurrence.seen_at),
                }
                for occurrence in session.scalars(
                    select(CollectionSeedOccurrence)
                    .where(CollectionSeedOccurrence.item_id == safe_item_id)
                    .order_by(CollectionSeedOccurrence.seen_at.desc(), CollectionSeedOccurrence.id.desc())
                    .limit(100)
                ).all()
            ]
            flat_item = self.get_flat_item(safe_item_id)
        artifacts = item_payload.get("artifacts") or {}
        artifact_contents = {
            "detail_html": self._read_collection_artifact(artifacts.get("detail_html_path"), max_chars=safe_max_chars),
            "description_json": self._read_collection_artifact(
                artifacts.get("description_json_path"), max_chars=safe_max_chars
            ),
            "selected_json": self._read_collection_artifact(artifacts.get("selected_json_path"), max_chars=safe_max_chars),
            "final_json": self._read_collection_artifact(artifacts.get("final_json_path"), max_chars=safe_max_chars),
        }
        return {
            "found": True,
            "item_id": safe_item_id,
            "max_chars": safe_max_chars,
            "item": item_payload,
            "occurrences": occurrences,
            "flat_item": flat_item,
            "artifacts": artifact_contents,
        }

    def requeue_seed_detail_analysis(self, item_id: str, *, reason: str = "operator_requested") -> Dict[str, Any]:
        safe_item_id = str(item_id or "").strip()
        if not self.enabled or not safe_item_id:
            return {"ok": False, "item_id": safe_item_id, "error": "item_id is required"}
        self.initialize()
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(CollectionSeedItem, safe_item_id)
            if row is None:
                return {"ok": False, "item_id": safe_item_id, "error": "item not found"}
            artifacts = self._seed_artifacts_from_row(row)
            if not artifacts.get("detail_html_path") and not artifacts.get("selected_json_path"):
                return {
                    "ok": False,
                    "item_id": safe_item_id,
                    "error": "detail artifacts are required before AI reanalysis",
                }
            payload = dict(row.source_payload or {})
            attempt_count = int(payload.get("_analysis_attempt_count") or 0)
            payload["_manual_reanalysis_requested_at"] = self._fmt_dt(now)
            payload["_manual_reanalysis_reason"] = str(reason or "operator_requested")
            row.source_payload = payload
            row.status = "raw_detail_captured"
            row.detail_leased_by = None
            row.detail_lease_until = None
            row.detail_last_error = None
            session.add(row)
            return {
                "ok": True,
                "item_id": safe_item_id,
                "status": row.status,
                "reason": payload["_manual_reanalysis_reason"],
                "analysis_attempt_count": attempt_count,
                "artifacts": artifacts,
            }

    def manual_update_flat_item(self, item_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        safe_item_id = str(item_id or "").strip()
        if not self.enabled or not safe_item_id:
            return {"ok": False, "item_id": safe_item_id, "error": "item_id is required"}
        if not isinstance(updates, dict) or not updates:
            return {"ok": False, "item_id": safe_item_id, "error": "updates must be a non-empty object"}
        existing = self.get_flat_item(safe_item_id)
        if existing is None:
            return {"ok": False, "item_id": safe_item_id, "error": "item not found"}

        normalized_updates = dict(updates)
        if "title" in normalized_updates:
            normalized_updates.setdefault("source_title", normalized_updates["title"])
        if "url" in normalized_updates:
            normalized_updates.setdefault("source_url", normalized_updates["url"])
        if "full_address" in normalized_updates:
            normalized_updates.setdefault("location", normalized_updates["full_address"])
        if "transaction_price" in normalized_updates:
            normalized_updates.setdefault("currentPrice", normalized_updates["transaction_price"])
        if "starting_price" in normalized_updates:
            normalized_updates.setdefault("initialPrice", normalized_updates["starting_price"])
        if "court_name" in normalized_updates:
            normalized_updates.setdefault("法院名称", normalized_updates["court_name"])

        merged = dict(existing)
        merged.update(normalized_updates)
        merged["id"] = safe_item_id
        merged["item_id"] = safe_item_id
        if "source_item_id" not in merged or not merged.get("source_item_id"):
            merged["source_item_id"] = safe_item_id
        self.upsert_flat_item(
            merged,
            event_type="manual_operator_update",
            event_payload={"item_id": safe_item_id, "updated_fields": sorted(str(key) for key in normalized_updates)},
        )
        return {
            "ok": True,
            "item_id": safe_item_id,
            "updated_fields": sorted(str(key) for key in normalized_updates),
            "flat_item": self.get_flat_item(safe_item_id),
        }

    def seed_queue_counts(self) -> Dict[str, int]:
        counts = {
            "seed_scan_job_pending": 0,
            "seed_scan_job_in_progress": 0,
            "seed_scan_job_completed": 0,
            "seed_scan_job_blocked": 0,
            "seed_scan_progress_pending": 0,
            "seed_scan_progress_in_progress": 0,
            "seed_scan_progress_exhausted": 0,
            "seed_scan_progress_blocked": 0,
            "seed_item_pending_detail": 0,
            "seed_item_in_progress": 0,
            "seed_item_raw_detail_captured": 0,
            "seed_item_analysis_in_progress": 0,
            "seed_item_analysis_failed": 0,
            "seed_item_analysis_blocked": 0,
            "seed_item_detail_completed": 0,
            "seed_item_detail_failed": 0,
            "seed_item_detail_blocked": 0,
            "seed_occurrence_total": 0,
        }
        if not self.enabled:
            return counts
        self.initialize()
        with self.session_factory() as session:
            for status, count_value in session.execute(
                select(CollectionSeedScanJob.status, func.count(CollectionSeedScanJob.job_key)).group_by(CollectionSeedScanJob.status)
            ):
                key = f"seed_scan_job_{status}"
                if key in counts:
                    counts[key] = int(count_value or 0)
            for status, count_value in session.execute(
                select(CollectionSeedScanProgress.status, func.count(CollectionSeedScanProgress.progress_key)).group_by(CollectionSeedScanProgress.status)
            ):
                key = f"seed_scan_progress_{status}"
                if key in counts:
                    counts[key] = int(count_value or 0)
            for status, count_value in session.execute(
                select(CollectionSeedItem.status, func.count(CollectionSeedItem.item_id)).group_by(CollectionSeedItem.status)
            ):
                key = f"seed_item_{status}"
                if key in counts:
                    counts[key] = int(count_value or 0)
            counts["seed_occurrence_total"] = int(session.scalar(select(func.count()).select_from(CollectionSeedOccurrence)) or 0)
        return counts
