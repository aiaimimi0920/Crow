#!/usr/bin/env python3
"""审计最近窗口内 AVM 关键字段缺口与可回填性。"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_environment import getenv as project_getenv
from src.avm.canonical_mapper import map_raw_to_canonical
from src.storage.repository import create_repository_from_env
from tools.avm_data_loader import discover_raw_record_files, load_json_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计最近窗口内 AVM enrich 缺口")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--output-path", type=Path, default=Path("datas/avm/recent_gap_audit.json"))
    parser.add_argument("--sample-limit", type=int, default=30)
    return parser.parse_args()


def _env_flag(name: str, default: bool) -> bool:
    raw = project_getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _parse_file_date(path: Path) -> datetime | None:
    try:
        return datetime.strptime(path.stem, "%Y-%m-%d")
    except ValueError:
        return None


def _normalized_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"done", "成交", "true", "finished", "ended", "success"}:
        return "done"
    return text


def _is_done_like(row: dict[str, Any], canonical: dict[str, Any]) -> bool:
    if row.get("detail_captured") is True:
        return True
    if row.get("是否成交") is True:
        return True
    if _normalized_status(canonical.get("status") or row.get("status")) == "done":
        return True
    return False


def _has_replay_source(row: dict[str, Any]) -> bool:
    for key in ("url", "source_url", "原始网站"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return True
    item_id = row.get("id") or row.get("item_id")
    return item_id not in (None, "")


def _has_coordinate_infer_signal(row: dict[str, Any], canonical: dict[str, Any]) -> bool:
    if canonical.get("community_name") not in (None, "", "UNK"):
        return True
    if canonical.get("city") not in (None, "", "UNK") and canonical.get("district") not in (None, "", "UNK"):
        return True
    for key in ("full_address", "location", "地点", "title", "source_title"):
        value = canonical.get(key) if key in canonical else row.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _analysis_missing_fields(row: dict[str, Any], canonical: dict[str, Any]) -> list[str]:
    explicit = row.get("analysis_missing_fields")
    if isinstance(explicit, list):
        return [str(item) for item in explicit if str(item or "").strip()]
    if row.get("analysis_ready") is True:
        return []

    missing_fields: list[str] = []
    for field in ("auction_date", "area_sqm", "city", "district", "business_area"):
        if canonical.get(field) in (None, "", "UNK"):
            missing_fields.append(field)

    if not any(canonical.get(field) not in (None, "", "UNK") for field in ("transaction_price", "starting_price", "actual_paid_price", "evaluation_price")):
        missing_fields.append("price_anchor")

    detail_status = str(row.get("detail_status") or "").strip().lower()
    detail_ready = detail_status in {"archived", "enriched"} or bool(row.get("detail_captured")) or bool(row.get("detail_archive_path"))
    if not detail_ready:
        missing_fields.append("detail_stage")

    if _normalized_status(canonical.get("status") or row.get("status")) != "done":
        missing_fields.append("status")

    if canonical.get("latitude") in (None, "", "UNK") and canonical.get("community_name") in (None, "", "UNK"):
        missing_fields.append("location_precision")

    return missing_fields


def _iter_recent_rows(data_root: Path, window_days: int, prefer_db: bool | None = None) -> list[dict[str, Any]]:
    use_db = _env_flag("CROW_DB_PREFER_CONTROL_PLANE_SOURCE", False) if prefer_db is None else prefer_db
    if use_db:
        repo = create_repository_from_env()
        if repo.enabled:
            try:
                rows = repo.iter_recent_flat_items(window_days)
                result = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    file_path = row.get("__file_path") or row.get("json_file") or row.get("source_json_path") or ""
                    result.append(dict(row, __file_path=str(file_path)))
                return result
            except Exception:
                pass

    files = discover_raw_record_files(data_root)
    dated_files = [(path, _parse_file_date(path)) for path in files]
    dated_files = [(path, dt) for path, dt in dated_files if dt is not None]
    max_file_date = max((dt for _, dt in dated_files), default=None)
    if max_file_date is None:
        return []
    recent_start = max_file_date - timedelta(days=window_days - 1)

    rows: list[dict[str, Any]] = []
    for path, file_date in dated_files:
        if file_date < recent_start:
            continue
        payload = load_json_payload(path)
        if not isinstance(payload, list):
            continue
        for row in payload:
            if not isinstance(row, dict):
                continue
            enriched = dict(row)
            enriched["__file_path"] = str(path)
            rows.append(enriched)
    return rows


def build_recent_gap_audit(data_root: Path, window_days: int, sample_limit: int) -> dict[str, Any]:
    rows = _iter_recent_rows(data_root, window_days, prefer_db=True)
    missing_counter: Counter[str] = Counter()
    analysis_missing_counter: Counter[str] = Counter()
    recoverability_counter: Counter[str] = Counter()
    housing_counter: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    detail_archive_present = 0
    detail_captured = 0

    for row in rows:
        try:
            canonical = map_raw_to_canonical(row)
        except Exception:
            continue

        if row.get("detail_captured") is True:
            detail_captured += 1
        detail_archive_path = row.get("detail_archive_path")
        archive_exists = False
        if detail_archive_path:
            archive_exists = (data_root / str(detail_archive_path)).exists()
        if archive_exists:
            detail_archive_present += 1

        housing_counter[str(canonical.get("housing_type") or "其他")] += 1

        missing_fields = []
        for field in ("latitude", "longitude", "is_occupied", "has_long_lease", "clear_delivery", "tax_burden", "is_fractional_share"):
            value = canonical.get(field)
            if value in (None, "", "UNK"):
                missing_counter[field] += 1
                missing_fields.append(field)

        analysis_missing_fields = _analysis_missing_fields(row, canonical)
        for field in analysis_missing_fields:
            analysis_missing_counter[field] += 1

        has_gap = bool(missing_fields or analysis_missing_fields)
        archive_backfill_candidate = bool(
            archive_exists and has_gap
        )
        replay_candidate = bool(
            has_gap
            and not archive_exists
            and _is_done_like(row, canonical)
            and _has_replay_source(row)
        )
        coordinate_infer_candidate = bool(
            has_gap
            and (
                "latitude" in missing_fields
                or "longitude" in missing_fields
                or "location_precision" in analysis_missing_fields
            )
            and _has_coordinate_infer_signal(row, canonical)
        )
        future_fixable = archive_backfill_candidate or replay_candidate or coordinate_infer_candidate
        historical_unrecoverable = has_gap and not future_fixable

        if archive_backfill_candidate:
            recoverability_counter["archive_backfill_candidate"] += 1
        if replay_candidate:
            recoverability_counter["replay_candidate"] += 1
        if coordinate_infer_candidate:
            recoverability_counter["coordinate_infer_candidate"] += 1
        if future_fixable:
            recoverability_counter["future_fixable"] += 1
        if historical_unrecoverable:
            recoverability_counter["historical_unrecoverable"] += 1

        if (missing_fields or analysis_missing_fields) and len(samples) < sample_limit:
            samples.append(
                {
                    "item_id": canonical.get("item_id"),
                    "file_path": row.get("__file_path"),
                    "auction_date": canonical.get("auction_date"),
                    "housing_type": canonical.get("housing_type"),
                    "detail_captured": row.get("detail_captured"),
                    "detail_archive_path": detail_archive_path,
                    "detail_archive_exists": archive_exists,
                    "missing_fields": missing_fields,
                    "analysis_missing_fields": analysis_missing_fields,
                    "future_fixable": future_fixable,
                    "historical_unrecoverable": historical_unrecoverable,
                    "archive_backfill_candidate": archive_backfill_candidate,
                    "replay_candidate": replay_candidate,
                    "coordinate_infer_candidate": coordinate_infer_candidate,
                    "title": row.get("title"),
                    "location": row.get("地点"),
                }
            )

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": window_days,
        "record_count": len(rows),
        "detail_captured_count": detail_captured,
        "detail_archive_present_count": detail_archive_present,
        "housing_type_counts": dict(housing_counter.most_common()),
        "missing_field_counts": dict(missing_counter),
        "analysis_missing_field_counts": dict(analysis_missing_counter),
        "recoverability_counts": dict(recoverability_counter),
        "samples": samples,
    }
    return output


def main() -> None:
    args = parse_args()
    report = build_recent_gap_audit(args.data_root, args.window_days, args.sample_limit)
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
