#!/usr/bin/env python3
"""为 recent 缺 enrich 且仍保留原始 URL 的记录准备 detail 重抓任务。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.collection_job_control import job_checkpoint
from src.storage.repository import create_repository_from_env
from tools.audit_recent_avm_gaps import _iter_recent_rows


REPLAY_VERSION = "detail_replay_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="准备 recent detail 重抓任务")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-path", type=Path, default=Path("datas/avm/recent_detail_replay.json"))
    return parser.parse_args()


def _load_file_rows(file_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _has_missing_enrich_fields(row: dict[str, Any]) -> bool:
    for key in ("latitude", "longitude", "纬度", "经度", "is_occupied", "has_long_lease", "clear_delivery", "tax_burden", "is_fractional_share", "avm_risk_features"):
        value = row.get(key)
        if key == "avm_risk_features":
            if not isinstance(value, dict) or not any(
                value.get(field) not in (None, "", "UNK")
                for field in ("is_occupied", "has_long_lease", "clear_delivery", "tax_burden", "is_fractional_share")
            ):
                return True
            continue
        if value in (None, "", "UNK"):
            return True
    return False


def _is_done_like(row: dict[str, Any]) -> bool:
    if row.get("detail_captured") is True:
        return True
    status = str(row.get("status") or "").lower()
    if status in {"done", "成交", "ended", "finished", "success", "successful"}:
        return True
    if row.get("是否成交") is True:
        return True
    return False


def _resolve_detail_url(row: dict[str, Any]) -> str | None:
    for key in ("url", "source_url", "原始网站"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    item_id = row.get("id") or row.get("item_id")
    if item_id not in (None, ""):
        return f"https://sf-item.taobao.com/sf_item/{item_id}.htm"
    return None


def prepare_recent_detail_replay(
    data_root: Path,
    window_days: int,
    limit: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    job_checkpoint()
    repo = create_repository_from_env()
    rows = _iter_recent_rows(data_root, window_days, prefer_db=True)
    by_file: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        job_checkpoint()
        file_path = row.get("__file_path")
        if isinstance(file_path, str):
            by_file.setdefault(file_path, []).append(row)

    prepared_count = 0
    touched_files = 0
    candidates = 0
    samples: list[dict[str, Any]] = []

    for file_path_str in sorted(by_file):
        job_checkpoint()
        file_path = Path(file_path_str)
        file_rows = _load_file_rows(file_path)
        changed = False
        changed_rows: list[dict[str, Any]] = []
        for row in file_rows:
            job_checkpoint()
            if prepared_count >= limit:
                break
            if not _is_done_like(row):
                continue
            if row.get("detail_archive_path"):
                continue
            if not _has_missing_enrich_fields(row):
                continue
            detail_url = _resolve_detail_url(row)
            if not detail_url:
                continue

            candidates += 1
            if row.get("detail_replay_requested_at"):
                continue

            if not dry_run:
                row["url"] = detail_url
                row["is_processed"] = False
                row["detail_replay_requested_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                row["detail_replay_reason"] = "missing_enrich_fields"
                row["detail_replay_version"] = REPLAY_VERSION
                changed = True
                changed_rows.append(row)

            prepared_count += 1
            if len(samples) < 30:
                samples.append(
                    {
                        "file_path": str(file_path),
                        "item_id": str(row.get("id") or row.get("item_id") or ""),
                        "detail_url": detail_url,
                        "detail_captured": row.get("detail_captured"),
                    }
                )

        if changed:
            job_checkpoint()
            touched_files += 1
            file_path.write_text(json.dumps(file_rows, ensure_ascii=False, indent=4), encoding="utf-8")
            if repo.enabled and changed_rows:
                repo.upsert_flat_items(
                    changed_rows,
                    event_type="detail_replay_prepared",
                    event_payload_factory=lambda record, _idx, file_path=file_path: {
                        "source_file": str(file_path),
                        "item_id": record["source"]["item_id"],
                    },
                )
        if prepared_count >= limit:
            break

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": window_days,
        "limit": limit,
        "dry_run": dry_run,
        "candidate_count": candidates,
        "prepared_count": prepared_count,
        "touched_files": touched_files,
        "samples": samples,
    }


def main() -> None:
    args = parse_args()
    report = prepare_recent_detail_replay(
        data_root=args.data_root,
        window_days=args.window_days,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
