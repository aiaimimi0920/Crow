"""Prepare detail capture retries using the active source's completion rules."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.archive_json_io import read_records
from src.collection_job_control import job_checkpoint
from src.storage.repository import (
    CollectionRepository,
    create_collection_repository_from_env,
)

from .adapter_resolver import collection_adapter_from_env
from .archive_records import apply_record_patch, iter_recent_rows, publish_records
from .contracts import CollectionAdapter, Record

REPLAY_VERSION = "detail_replay_v1"


def prepare_recent_detail_replay(
    data_root: Path,
    window_days: int,
    limit: int,
    dry_run: bool = False,
    *,
    repository: CollectionRepository | None = None,
    adapter: CollectionAdapter | None = None,
) -> Record:
    job_checkpoint()
    selected = adapter or collection_adapter_from_env(default="taobao_judicial")
    repo = (
        repository
        if repository is not None
        else create_collection_repository_from_env(adapter=selected)
    )
    by_file: dict[str, dict[str, Record]] = {}
    for row in iter_recent_rows(data_root, window_days, repo):
        job_checkpoint()
        path = row.get("__file_path")
        if isinstance(path, str) and path:
            by_file.setdefault(path, {})[selected.item_id(row)] = row
    prepared = candidates = touched = 0
    samples: list[Record] = []
    for path_value, ids in sorted(by_file.items()):
        job_checkpoint()
        if prepared >= limit:
            break
        path = Path(path_value)
        rows = read_records(path)
        changed: list[Record] = []
        for row in rows:
            job_checkpoint()
            if prepared >= limit:
                break
            if selected.item_id(row) not in ids:
                continue
            reason = selected.detail_replay_reason(row)
            url = selected.detail_replay_url(row)
            if not reason or not url:
                continue
            candidates += 1
            requested = row.get("detail_replay_requested_at")
            if requested:
                saved = ids[selected.item_id(row)]
                if (
                    not repo.enabled
                    or saved.get("detail_replay_requested_at") == requested
                ):
                    continue
            if not dry_run:
                if not requested:
                    apply_record_patch(
                        row,
                        {
                            "url": url,
                            "is_processed": False,
                            "detail_replay_requested_at": datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            "detail_replay_reason": reason,
                            "detail_replay_version": REPLAY_VERSION,
                        },
                    )
                changed.append(row)
            prepared += 1
            if len(samples) < 30:
                samples.append(
                    {
                        "file_path": str(path),
                        "item_id": selected.item_id(row),
                        "detail_url": url,
                        "detail_captured": row.get("detail_captured"),
                    }
                )
        if changed:
            publish_records(path, rows, changed, repo, "detail_replay_prepared")
            touched += 1
    return {
        "generated_at": datetime.now().isoformat(),
        "window_days": window_days,
        "limit": limit,
        "dry_run": dry_run,
        "candidate_count": candidates,
        "prepared_count": prepared,
        "touched_files": touched,
        "samples": samples,
    }
