from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .models import CollectionAnalysisRun, CollectionSeedItem
from .repository_context import _resolve_collection_artifact_path, _utc_now


class RepositoryDetailAnalysisMixin:
    def mark_seed_detail_analysis_failed(
        self,
        item_id: str,
        error: str,
        *,
        retryable: bool = True,
        revert_attempt: bool = False,
        restore_raw: bool = False,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        with self.session_factory.begin() as session:
            row = session.get(CollectionSeedItem, str(item_id))
            if row is None:
                return
            row.status = "raw_detail_captured" if restore_raw else "analysis_failed" if retryable else "analysis_blocked"
            row.detail_leased_by = None
            row.detail_lease_until = None
            row.detail_last_error = str(error)
            if revert_attempt:
                payload = dict(row.source_payload or {})
                payload["_analysis_attempt_count"] = max(int(payload.get("_analysis_attempt_count") or 0) - 1, 0)
                row.source_payload = payload
            session.add(row)

    def record_analysis_ensemble_run(self, item_id: str, receipt: Dict[str, Any]) -> None:
        """Persist module B audit metadata without touching module A queue state."""
        if not self.enabled:
            return
        self.initialize()
        payload = dict(receipt or {})
        run_id = str(payload.get("run_id") or "").strip()
        pipeline_version = str(payload.get("schema_version") or "").strip()
        input_sha256 = str(payload.get("input_sha256") or "").strip()
        if not run_id or not pipeline_version or not input_sha256:
            raise ValueError("analysis ensemble receipt requires run_id, schema_version, and input_sha256")

        status = str(payload.get("status") or "failed").strip()
        error = payload.get("error")
        if isinstance(error, (dict, list)):
            error_text = json.dumps(error, ensure_ascii=False, sort_keys=True)
        else:
            error_text = str(error or "").strip() or None
        terminal_statuses = {"finalized", "needs_review", "candidate_partial", "adjudication_failed", "failed"}
        with self.session_factory.begin() as session:
            row = session.get(CollectionAnalysisRun, run_id)
            if row is None:
                row = CollectionAnalysisRun(
                    run_id=run_id,
                    item_id=str(item_id),
                    pipeline_version=pipeline_version,
                    input_sha256=input_sha256,
                    mode=str(payload.get("mode") or "shadow"),
                    status=status,
                )
            row.item_id = str(item_id)
            row.pipeline_version = pipeline_version
            row.input_sha256 = input_sha256
            row.mode = str(payload.get("mode") or "shadow")
            row.status = status
            row.candidate_models = list(payload.get("candidate_models") or [])
            row.arbiter_model = str(payload.get("arbiter_model") or "").strip() or None
            independent = payload.get("arbiter_independent_model")
            row.arbiter_independent_model = bool(independent) if independent is not None else None
            row.artifact_paths = dict(payload.get("artifacts") or {})
            row.receipt = payload
            row.error = error_text
            if status in terminal_statuses:
                row.completed_at = _utc_now()
            session.add(row)

    def get_analysis_ensemble_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        with self.session_factory() as session:
            row = session.get(CollectionAnalysisRun, str(run_id))
            if row is None:
                return None
            return {
                "run_id": row.run_id,
                "item_id": row.item_id,
                "pipeline_version": row.pipeline_version,
                "input_sha256": row.input_sha256,
                "mode": row.mode,
                "status": row.status,
                "candidate_models": list(row.candidate_models or []),
                "arbiter_model": row.arbiter_model,
                "arbiter_independent_model": row.arbiter_independent_model,
                "artifact_paths": dict(row.artifact_paths or {}),
                "receipt": dict(row.receipt or {}),
                "error": row.error,
                "completed_at": row.completed_at,
            }

    def mark_seed_detail_failed(
        self,
        item_id: str,
        error: str,
        *,
        retryable: bool = True,
        revert_attempt: bool = False,
        restore_pending: bool = False,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        with self.session_factory.begin() as session:
            row = session.get(CollectionSeedItem, str(item_id))
            if row is None:
                return
            if restore_pending:
                row.status = "pending_detail"
            else:
                row.status = "detail_failed" if retryable else "detail_blocked"
            row.detail_leased_by = None
            row.detail_lease_until = None
            row.detail_last_error = str(error)
            if revert_attempt:
                row.detail_attempt_count = max(int(row.detail_attempt_count or 0) - 1, 0)
            session.add(row)

    @staticmethod
    def _seed_artifacts_from_row(row: CollectionSeedItem) -> Dict[str, str | None]:
        payload = dict(row.source_payload or {})
        artifacts = dict(payload.get("_raw_detail_artifacts") or {})
        if row.selected_json_path:
            artifacts["selected_json_path"] = row.selected_json_path
        if row.final_json_path:
            artifacts["final_json_path"] = row.final_json_path

        # Older completed rows sometimes retained only final/selected paths.
        # Derive sibling raw artifacts when they are present so the observer can
        # still show the collected source rather than reporting a false gap.
        final_path = str(artifacts.get("final_json_path") or "").strip()
        if final_path:
            normalized_final = final_path.replace("\\", "/")
            parent = normalized_final.rsplit("/", 1)[0] if "/" in normalized_final else ""
            parent_candidates = [parent] if parent else []
            if "/detail_analysis_worker" in parent:
                parent_candidates.append(parent.replace("/detail_analysis_worker", "/detail_worker", 1))
            for candidate_parent in parent_candidates:
                for key, filename in (
                    ("detail_html_path", "detail.html"),
                    ("description_json_path", "description-data.json"),
                ):
                    if artifacts.get(key):
                        continue
                    candidate = f"{candidate_parent}/{filename}"
                    if _resolve_collection_artifact_path(candidate):
                        artifacts[key] = candidate
        return {
            "detail_html_path": artifacts.get("detail_html_path"),
            "description_json_path": artifacts.get("description_json_path"),
            "selected_json_path": artifacts.get("selected_json_path"),
            "final_json_path": artifacts.get("final_json_path"),
        }
