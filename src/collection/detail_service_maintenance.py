from __future__ import annotations

from typing import Any

from .detail_execution import DetailModels, DetailRuntime, DetailStorage
from .detail_processor import DetailProcessor


class DetailServiceMaintenanceMixin:
    def process_html_file(
        self,
        file_path: str,
        *,
        storage: DetailStorage,
        runtime: DetailRuntime,
        models: DetailModels,
    ) -> None:
        DetailProcessor(
            data_root=self.data_root,
            retry_dir=self.retry_dir,
            adapter=self.adapter,
            capture_lock=self._dispatch_lock,
        ).process(
            file_path,
            storage=storage,
            runtime=runtime,
            models=models,
        )

    def fetch_missing_archives(
        self,
        *,
        limit: int = 20,
        timeout: int = 15,
        extract_risk: bool = False,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        from src.collection.detail_archive_fetch import fetch_missing_detail_archives

        return fetch_missing_detail_archives(
            data_root=self.data_root,
            limit=limit,
            timeout=timeout,
            extract_risk=extract_risk,
            dry_run=dry_run,
            repository=self.repository,
            adapter=self.adapter,
        )

    def backfill_archived(
        self,
        *,
        limit: int = 200,
        dry_run: bool = True,
        extract_risk: bool = False,
    ) -> dict[str, Any]:
        from .detail_backfill import backfill_archived_details

        return backfill_archived_details(
            self.data_root,
            limit=limit,
            dry_run=dry_run,
            extract_risk=extract_risk,
            repository=self.repository,
            adapter=self.adapter,
        )

    def prepare_replay(
        self,
        *,
        window_days: int = 7,
        limit: int = 100,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        from .detail_replay import prepare_recent_detail_replay

        return prepare_recent_detail_replay(
            self.data_root,
            window_days=window_days,
            limit=limit,
            dry_run=dry_run,
            repository=self.repository,
            adapter=self.adapter,
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
    ) -> dict[str, Any]:
        from .detail_maintenance import run_collection_maintenance

        return run_collection_maintenance(
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
            repository=self.repository,
            adapter=self.adapter,
        )


__all__ = ["DetailServiceMaintenanceMixin"]
