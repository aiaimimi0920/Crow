#!/usr/bin/env python3
"""用现有 centroid 兜底能力回填 recent 样本的坐标字段。"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.avm.canonical_mapper import map_raw_to_canonical
from src.avm.feature_builder import build_features
from src.avm.service import AVMService
from src.storage.repository import create_repository_from_env
from tools.audit_recent_avm_gaps import _iter_recent_rows
from tools.maintenance_diagnostics import coordinate_summary

BACKFILL_VERSION = "coord_backfill_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回填 recent 样本坐标")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-path", type=Path, default=Path("datas/avm/recent_coordinate_backfill.json"))
    return parser.parse_args()


def _load_file_rows(file_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def backfill_recent_coordinates(data_root: Path, window_days: int, dry_run: bool = False) -> dict[str, Any]:
    repo = create_repository_from_env()
    service = AVMService(data_dir=str(data_root), repository=repo)
    service.ensure_coordinate_cache(allow_file_fallback=not bool(service.repository and getattr(service.repository, "enabled", False)))

    rows = _iter_recent_rows(data_root, window_days, prefer_db=True)
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        file_path = row.get("__file_path")
        if isinstance(file_path, str):
            by_file[file_path].append(row)

    updated_records: list[dict[str, Any]] = []
    updated_count = 0
    candidate_count = 0

    for file_path_str, _ in by_file.items():
        file_path = Path(file_path_str)
        file_rows = _load_file_rows(file_path)
        changed = False
        changed_rows: list[dict[str, Any]] = []

        for row in file_rows:
            try:
                canonical = map_raw_to_canonical(row)
                feature = build_features(canonical)
            except Exception:
                continue

            has_lat = isinstance(canonical.get("latitude"), (int, float))
            has_lon = isinstance(canonical.get("longitude"), (int, float))
            if has_lat and has_lon:
                continue

            candidate_count += 1
            enriched = service._enrich_coordinates(feature, service._centroid_cache or {})
            strategy = enriched.get("coordinate_strategy")
            lat = enriched.get("latitude")
            lon = enriched.get("longitude")
            if strategy in (None, "missing", "observed"):
                continue
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                continue

            row["latitude"] = round(float(lat), 6)
            row["longitude"] = round(float(lon), 6)
            row["纬度"] = row["latitude"]
            row["经度"] = row["longitude"]
            row["coordinate_backfill_strategy"] = strategy
            row["coordinate_backfill_version"] = BACKFILL_VERSION
            changed = True
            changed_rows.append(row)
            updated_count += 1
            if len(updated_records) < 30:
                updated_records.append(
                    {
                        "file_path": str(file_path),
                        "item_id": canonical.get("item_id"),
                        "strategy": strategy,
                        "latitude": row["latitude"],
                        "longitude": row["longitude"],
                    }
                )

        if changed and not dry_run:
            file_path.write_text(json.dumps(file_rows, ensure_ascii=False, indent=4), encoding="utf-8")
            if repo.enabled and changed_rows:
                repo.upsert_flat_items(
                    changed_rows,
                    event_type="recent_coordinate_backfill",
                    event_payload_factory=lambda record, _idx, file_path=file_path: {
                        "source_file": str(file_path),
                        "item_id": record["source"]["item_id"],
                    },
                )

    return {
        "window_days": window_days,
        "dry_run": dry_run,
        "candidate_count": candidate_count,
        "updated_count": updated_count,
        "updated_records": updated_records,
    }


def main() -> None:
    args = parse_args()
    report = backfill_recent_coordinates(args.data_root, args.window_days, args.dry_run)
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(coordinate_summary(report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
