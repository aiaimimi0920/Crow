"""Recover factual fields from retained evidence without invoking analysis."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from src import llm_helper
from src.archive_json_io import read_records
from src.collection_job_control import job_checkpoint
from src.detail_artifacts import extract_detail_artifacts
from src.storage.repository import (
    CollectionRepository,
    create_collection_repository_from_env,
)

from .adapter_resolver import collection_adapter_from_env
from .adapters.taobao_detail_facts import merge_risk_features, needs_risk_enrich
from .archive_records import (
    apply_record_patch,
    discover_raw_record_files,
    load_json_payload,
    publish_records,
)
from .contracts import CollectionAdapter, Record


def _iter_rows(data_root: Path) -> list[tuple[Path, list[Record]]]:
    rows = []
    for path in discover_raw_record_files(data_root):
        job_checkpoint()
        payload = load_json_payload(path)
        if isinstance(payload, list):
            rows.append((path, [row for row in payload if isinstance(row, dict)]))
    return rows


def backfill_archived_details(
    data_root: Path,
    limit: int,
    dry_run: bool = False,
    extract_risk: bool = False,
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
    if repo.enabled:
        candidates = repo.iter_archived_detail_candidates(
            limit=limit,
            require_missing_coordinates=True,
            require_missing_risk=extract_risk and selected.collects_avm_risk,
        )
        grouped: dict[str, list[Record]] = {}
        for candidate_row in candidates:
            path = (
                candidate_row.get("__file_path")
                or candidate_row.get("json_file")
                or candidate_row.get("source_json_path")
            )
            if isinstance(path, str) and path:
                grouped.setdefault(path, []).append(candidate_row)
        source_rows = [(Path(path), rows) for path, rows in sorted(grouped.items())]
    else:
        source_rows = _iter_rows(data_root)
    scanned = updated = touched = ai_calls = planned = 0
    samples: list[Record] = []
    for path, candidates in source_rows:
        job_checkpoint()
        if scanned >= limit:
            break
        rows = read_records(path)
        indexed = {selected.item_id(row): row for row in rows}
        changed: list[Record] = []
        for candidate in candidates:
            job_checkpoint()
            if scanned >= limit:
                break
            item_id = selected.item_id(candidate)
            row = indexed.get(item_id)
            if row is None:
                continue
            archive = row.get("detail_archive_path") or candidate.get(
                "detail_archive_path"
            )
            if not archive or not (data_root / str(archive)).is_file():
                continue
            scanned += 1
            content = (data_root / str(archive)).read_text(
                encoding="utf-8", errors="replace"
            )
            revision = uuid4().hex
            fields = extract_detail_artifacts(
                data_root=data_root,
                html_content=content,
                item_id=item_id,
                auction_date=selected.archive_date(row),
                source_url=selected.source_url(row),
                archive_revision=revision,
                dry_run=True,
            )
            patch = {
                key: value
                for key, value in fields.items()
                if value not in (None, "", []) and row.get(key) in (None, "", [])
            }
            if patch and not dry_run:
                job_checkpoint()
                extract_detail_artifacts(
                    data_root=data_root,
                    html_content=content,
                    item_id=item_id,
                    auction_date=selected.archive_date(row),
                    source_url=selected.source_url(row),
                    archive_revision=revision,
                )
            if row.get("latitude") in (None, "") or row.get("longitude") in (None, ""):
                coord = llm_helper.extract_property_coordinates(content)
                if coord:
                    lat, lon = (
                        round(float(coord["latitude"]), 6),
                        round(float(coord["longitude"]), 6),
                    )
                    patch.update(
                        latitude=lat,
                        longitude=lon,
                        coordinate_backfill_strategy="archived_detail_html",
                    )
                    patch.update({"纬度": lat, "经度": lon})
            risk_needed = (
                extract_risk and selected.collects_avm_risk and needs_risk_enrich(row)
            )
            if risk_needed and not dry_run:
                job_checkpoint()
                extracted = llm_helper.extract_avm_risk_features(
                    content, item_id=item_id
                )
                ai_calls += 1
                job_checkpoint()
                if extracted:
                    merge_risk_features(patch, extracted)
            pending_publication = repo.enabled and any(
                row.get(key) not in (None, "", [])
                and row.get(key) != candidate.get(key)
                for key in (*fields, "latitude", "longitude", "avm_risk_features")
            )
            if patch or risk_needed or pending_publication:
                planned += 1
                if not dry_run and (patch or pending_publication):
                    apply_record_patch(row, patch)
                    changed.append(row)
                    updated += 1
                if len(samples) < 20:
                    samples.append(
                        {
                            "file_path": str(path),
                            "item_id": item_id,
                            "detail_archive_path": str(archive),
                            "risk_extraction_planned": risk_needed,
                        }
                    )
        if changed:
            publish_records(path, rows, changed, repo, "archived_detail_backfill")
            touched += 1
    return {
        "limit": limit,
        "dry_run": dry_run,
        "extract_risk": extract_risk,
        "scanned_archives": scanned,
        "updated_records": updated,
        "planned_count": planned,
        "touched_files": touched,
        "ai_calls": ai_calls,
        "samples": samples,
    }
