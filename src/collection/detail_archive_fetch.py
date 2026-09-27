"""Fetch missing detail HTML archives for DB-selected candidates and sync JSON + DB."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import cast

import requests

from src.collection_job_control import job_checkpoint, job_io_timeout
from src.detail_artifacts import extract_detail_artifacts, get_detail_archive_path
from src.llm_helper import (
    extract_avm_risk_features,
    extract_property_coordinates,
    filter_content,
)
from src.storage.repository import create_repository_from_env

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def _blocked_reason_for_html(html_content: str) -> str | None:
    text = str(html_content or "")
    lowered = text.lower()
    if (
        "login.taobao.com/member/login.jhtml" in lowered
        or "login.m.taobao.com/login.htm" in lowered
    ):
        return "login_redirect"
    if (
        "_____tmd_____" in lowered
        or "sdklogin" in lowered
        or "localstorage.x5referer" in lowered
    ):
        return "anti_bot_gate"
    if len(text.strip()) < 200:
        return "empty_html"
    return None


def _load_file_rows(file_path: Path) -> list[dict[str, object]]:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _needs_risk_enrich(row: dict[str, object]) -> bool:
    risk_payload = row.get("avm_risk_features")
    if not isinstance(risk_payload, dict):
        return True
    return not any(
        risk_payload.get(key) not in (None, "", "UNK")
        for key in (
            "is_occupied",
            "has_long_lease",
            "clear_delivery",
            "tax_burden",
            "is_fractional_share",
        )
    )


def _merge_risk_features(row: dict[str, object], extracted: dict[str, object]) -> None:
    row["avm_risk_features"] = extracted
    for key in (
        "community_name",
        "build_year",
        "total_floors",
        "floor_level",
        "has_elevator",
        "orientation",
        "land_right_type",
        "is_occupied",
        "has_long_lease",
        "clear_delivery",
        "tax_burden",
        "is_haunted",
        "housing_type",
        "has_keys",
        "property_fee_owed",
        "special_school_tag",
        "evaluation_price",
        "layout",
        "is_restricted_purchase",
        "includes_parking",
        "is_fractional_share",
        "tax_is_company_owned",
        "has_lease_before_mortgage",
        "extraction_confidence",
        "evidence_span",
        "evidence_source",
        "extraction_version",
    ):
        value = extracted.get(key)
        if value not in (None, "", "UNK"):
            row[key] = value


def fetch_missing_detail_archives(
    data_root: Path,
    limit: int,
    timeout: int,
    extract_risk: bool = False,
    dry_run: bool = False,
) -> dict[str, object]:
    job_checkpoint()
    repo = create_repository_from_env()
    candidates = repo.iter_detail_fetch_candidates(limit=limit) if repo.enabled else []
    fetched_count = 0
    touched_files = 0
    failed_count = 0
    blocked_count = 0
    samples: list[dict[str, object]] = []

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for candidate in candidates:
        job_checkpoint()
        file_path_value = (
            candidate.get("__file_path")
            or candidate.get("json_file")
            or candidate.get("source_json_path")
        )
        source_url = candidate.get("source_url") or candidate.get("url")
        item_id = str(candidate.get("item_id") or candidate.get("id") or "")
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
                        "error": str(exc),
                    },
                )
            if len(samples) < 20:
                samples.append(
                    {"item_id": item_id, "source_url": source_url, "error": str(exc)}
                )
            continue

        blocked_reason = _blocked_reason_for_html(html_content)
        if blocked_reason:
            blocked_count += 1
            if not dry_run:
                file_rows = _load_file_rows(file_path)
                blocked_row = None
                for row in file_rows:
                    if str(row.get("id") or row.get("item_id") or "") == item_id:
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
                        file_path.write_text(
                            json.dumps(file_rows, ensure_ascii=False, indent=4),
                            encoding="utf-8",
                        )
                        break
                if repo.enabled and isinstance(blocked_row, dict):
                    repo.upsert_flat_item(
                        blocked_row,
                        event_type="detail_archive_fetch_blocked",
                        event_payload={
                            "source_file": str(file_path),
                            "item_id": item_id,
                            "reason": blocked_reason,
                        },
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

        file_rows = _load_file_rows(file_path)
        target_row = None
        for row in file_rows:
            if str(row.get("id") or row.get("item_id") or "") == item_id:
                target_row = row
                break
        if not isinstance(target_row, dict):
            continue

        archive_path = get_detail_archive_path(
            data_root, candidate.get("auction_date"), item_id
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

        coord = extract_property_coordinates(html_content)
        if coord:
            target_row["latitude"] = coord["latitude"]
            target_row["longitude"] = coord["longitude"]
            target_row["纬度"] = coord["latitude"]
            target_row["经度"] = coord["longitude"]
            target_row["coordinate_source"] = "html"
        artifact_fields = extract_detail_artifacts(
            data_root=data_root,
            html_content=html_content,
            item_id=item_id,
            auction_date=candidate.get("auction_date"),
            source_url=str(source_url),
        )
        for key, value in artifact_fields.items():
            if value not in (None, "", []):
                target_row[key] = value
        risk_extracted = False
        if extract_risk and _needs_risk_enrich(target_row):
            job_checkpoint()
            page_text = filter_content(html_content)
            extracted_risk = extract_avm_risk_features(page_text, item_id=item_id)
            if isinstance(extracted_risk, dict):
                _merge_risk_features(target_row, extracted_risk)
                risk_extracted = True

        if not dry_run:
            job_checkpoint()
            archive_path.write_text(html_content, encoding="utf-8")
            file_path.write_text(
                json.dumps(file_rows, ensure_ascii=False, indent=4), encoding="utf-8"
            )
            if repo.enabled:
                repo.upsert_flat_items(
                    [target_row],
                    event_type="detail_archive_fetched",
                    event_payload_factory=lambda record, _idx, file_path=file_path: {
                        "source_file": str(file_path),
                        "item_id": record["source"]["item_id"],
                    },
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
        "samples": samples,
    }
