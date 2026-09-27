"""Explicit collection maintenance steps; no analysis recommendations or readiness."""

from pathlib import Path

from src.collection_job_control import job_checkpoint
from src.storage.repository import (
    CollectionRepository,
    create_collection_repository_from_env,
)

from .adapter_resolver import collection_adapter_from_env
from .contracts import CollectionAdapter, Record
from .detail_archive_fetch import fetch_missing_detail_archives
from .detail_backfill import backfill_archived_details
from .detail_replay import prepare_recent_detail_replay


def run_collection_maintenance(
    data_root: Path,
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
    *,
    repository: CollectionRepository | None = None,
    adapter: CollectionAdapter | None = None,
) -> Record:
    # Legacy request fields remain accepted; they never enable postprocessing.
    selected = adapter or collection_adapter_from_env(default="taobao_judicial")
    repo = (
        repository
        if repository is not None
        else create_collection_repository_from_env(adapter=selected)
    )
    job_checkpoint()
    fetched = (
        fetch_missing_detail_archives(
            data_root,
            fetch_limit,
            fetch_timeout,
            extract_risk,
            dry_run,
            repository=repo,
            adapter=selected,
        )
        if fetch_archives
        else {"skipped": True, "fetched_count": 0}
    )
    job_checkpoint()
    archived = backfill_archived_details(
        data_root,
        archive_limit,
        dry_run,
        extract_risk,
        repository=repo,
        adapter=selected,
    )
    job_checkpoint()
    replay = (
        prepare_recent_detail_replay(
            data_root,
            window_days,
            replay_limit,
            dry_run,
            repository=repo,
            adapter=selected,
        )
        if prepare_replay
        else {"skipped": True, "prepared_count": 0}
    )
    job_checkpoint()
    return {
        "dry_run": dry_run,
        "detail_archive_fetch": fetched,
        "archived_detail_backfill": archived,
        "detail_replay_preparation": replay,
        "ai_calls": fetched.get("ai_calls", 0) + archived.get("ai_calls", 0),
    }
