"""Fetch missing detail HTML archives for DB-selected candidates and sync JSON + DB."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import requests

from src.archive_json_io import read_records as _load_file_rows
from src.archive_json_io import write_text
from src.collection_job_control import job_checkpoint, job_io_timeout
from src.detail_artifacts import extract_detail_artifacts, get_detail_archive_path
from src.llm_helper import (
    extract_avm_risk_features,
    extract_property_coordinates,
    filter_content,
)
from src.storage.repository import (
    CollectionRepository,
    create_collection_repository_from_env,
)

from .adapter_resolver import collection_adapter_from_env
from .adapters.taobao_detail_facts import (
    merge_risk_features as _merge_risk_features,
)
from .adapters.taobao_detail_facts import (
    needs_risk_enrich as _needs_risk_enrich,
)
from .archive_records import apply_record_patch, publish_records
from .contracts import CollectionAdapter

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def fetch_missing_detail_archives(
    data_root: Path,
    limit: int,
    timeout: int,
    extract_risk: bool = False,
    dry_run: bool = False,
    *,
    repository: CollectionRepository | None = None,
    adapter: CollectionAdapter | None = None,
) -> dict[str, object]:
    job_checkpoint()
    selected = adapter or collection_adapter_from_env(default="taobao_judicial")
    repo = (
        repository
        if repository is not None
        else create_collection_repository_from_env(adapter=selected)
    )
    candidates = repo.iter_detail_fetch_candidates(limit=limit) if repo.enabled else []
    fetched_count = 0
    touched_files = 0
    failed_count = 0
    blocked_count = 0
    samples: list[dict[str, object]] = []

    if dry_run:
        return {
            "limit": limit,
            "timeout": timeout,
            "extract_risk": extract_risk,
            "dry_run": True,
            "candidate_count": len(candidates),
            "planned_count": len(candidates),
            "fetched_count": 0,
            "failed_count": 0,
            "blocked_count": 0,
            "touched_files": 0,
            "ai_calls": 0,
            "samples": [
                {"item_id": str(row.get("item_id") or row.get("id") or "")}
                for row in candidates[:20]
            ],
        }

    ai_calls = 0
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for candidate in candidates:
        job_checkpoint()
        file_path_value = (
            candidate.get("__file_path")
            or candidate.get("json_file")
            or candidate.get("source_json_path")
        )
        source_url = selected.source_url(candidate)
        item_id = selected.item_id(candidate)
        if (
            not item_id
            or not isinstance(file_path_value, str)
            or not file_path_value.strip()
            or not source_url
        ):
            continue

        file_path = Path(file_path_value)
        if not file_path.exists():
            continue

        file_rows = _load_file_rows(file_path)
        target_row = next(
            (row for row in file_rows if selected.item_id(row) == item_id), None
        )
        if target_row is None:
            continue
        previous_archive = target_row.get("detail_archive_path")
        if previous_archive and (data_root / str(previous_archive)).is_file():
            # A prior JSON publication may have succeeded before the DB failed.
            publish_records(
                file_path, file_rows, [target_row], repo, "detail_archive_fetched"
            )
            touched_files += 1
            fetched_count += 1
            continue

        try:
            response = session.get(str(source_url), timeout=job_io_timeout(timeout))
            response.raise_for_status()
            html_content = response.text
            job_checkpoint()
        except Exception as exc:
            job_checkpoint()
            failed_count += 1
            if repo.enabled and not dry_run:
                repo.upsert_flat_item(
                    candidate,
                    event_type="detail_archive_fetch_failed",
                    event_payload={
                        "source_file": str(file_path),
                        "item_id": item_id,
                        "error_type": type(exc).__name__,
                    },
                )
            if len(samples) < 20:
                samples.append({"item_id": item_id, "error_type": type(exc).__name__})
            continue

        blocked_reason = selected.blocked_capture_reason(html_content)
        if blocked_reason:
            blocked_count += 1
            if not dry_run:
                file_rows = _load_file_rows(file_path)
                blocked_row = None
                for row in file_rows:
                    if selected.item_id(row) == item_id:
                        row["detail_fetch_status"] = blocked_reason
                        row["detail_fetch_attempted_at"] = (
                            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        )
                        row["detail_fetch_attempt_count"] = (
                            int(
                                cast(
                                    "str | int",
                                    row.get("detail_fetch_attempt_count") or 0,
                                )
                            )
                            + 1
                        )
                        row["detail_fetch_last_url"] = str(source_url)
                        blocked_row = row
                        break
                if repo.enabled and isinstance(blocked_row, dict):
                    publish_records(
                        file_path,
                        file_rows,
                        [blocked_row],
                        repo,
                        "detail_archive_fetch_blocked",
                    )
            if len(samples) < 20:
                samples.append(
                    {
                        "item_id": item_id,
                        "source_url": source_url,
                        "blocked_reason": blocked_reason,
                    }
                )
            continue

        revision = uuid4().hex
        archive_date = selected.archive_date(candidate)
        archive_path = get_detail_archive_path(
            data_root, archive_date, item_id, revision=revision
        )
        relative_archive = archive_path.relative_to(data_root).as_posix()
        target_row["detail_archive_path"] = relative_archive
        target_row["detail_captured"] = True
        target_row["is_processed"] = False
        target_row["detail_fetch_status"] = "success"
        target_row["detail_fetch_attempted_at"] = datetime.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        target_row["detail_fetch_attempt_count"] = (
            int(cast("str | int", target_row.get("detail_fetch_attempt_count") or 0))
            + 1
        )
        target_row["detail_fetch_last_url"] = str(source_url)
        apply_record_patch(
            target_row,
            {
                "detail_archive_path": relative_archive,
                "detail_captured": True,
                "is_processed": False,
            },
        )

        coord = extract_property_coordinates(html_content)
        if coord:
            apply_record_patch(
                target_row,
                {
                    "latitude": coord["latitude"],
                    "longitude": coord["longitude"],
                    "纬度": coord["latitude"],
                    "经度": coord["longitude"],
                    "coordinate_source": "html",
                },
            )
        artifact_fields = extract_detail_artifacts(
            data_root=data_root,
            html_content=html_content,
            item_id=item_id,
            auction_date=archive_date,
            source_url=str(source_url),
            archive_revision=revision,
        )
        for key, value in artifact_fields.items():
            if value not in (None, "", []):
                apply_record_patch(target_row, {key: value})
        risk_extracted = False
        if (
            extract_risk
            and selected.collects_avm_risk
            and _needs_risk_enrich(target_row)
        ):
            job_checkpoint()
            page_text = filter_content(html_content)
            extracted_risk = extract_avm_risk_features(page_text, item_id=item_id)
            ai_calls += 1
            job_checkpoint()
            if isinstance(extracted_risk, dict):
                risk_patch: dict[str, object] = {}
                _merge_risk_features(risk_patch, extracted_risk)
                apply_record_patch(target_row, risk_patch)
                risk_extracted = True

        if not dry_run:
            job_checkpoint()
            write_text(archive_path, html_content)
            publish_records(
                file_path, file_rows, [target_row], repo, "detail_archive_fetched"
            )
            touched_files += 1

        fetched_count += 1
        if len(samples) < 20:
            samples.append(
                {
                    "item_id": item_id,
                    "source_url": source_url,
                    "detail_archive_path": relative_archive,
                    "has_coordinates": bool(coord),
                    "has_risk_features": risk_extracted,
                }
            )

    return {
        "limit": limit,
        "timeout": timeout,
        "extract_risk": extract_risk,
        "dry_run": dry_run,
        "candidate_count": len(candidates),
        "fetched_count": fetched_count,
        "failed_count": failed_count,
        "blocked_count": blocked_count,
        "touched_files": touched_files,
        "ai_calls": ai_calls,
        "samples": samples,
    }
