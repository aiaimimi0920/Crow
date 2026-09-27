#!/usr/bin/env python3
"""对已归档的详情页 HTML/TXT 回放坐标与可选风控抽取。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.collection.detail_backfill import backfill_archived_details


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回放 archived detail enrich")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(os.getenv("FAPAI_DATA_ROOT") or REPO_ROOT / "FPFData" / "datas"),
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--extract-risk", action="store_true", help="启用 LLM 风控抽取")
    parser.add_argument(
        "--output-path",
        type=Path,
    )
    args = parser.parse_args()
    if args.output_path is None:
        args.output_path = (
            args.data_root / "maintenance" / "archived_detail_backfill.json"
        )
    return args


def main() -> None:
    args = parse_args()
    report = backfill_archived_details(
        data_root=args.data_root,
        limit=args.limit,
        dry_run=args.dry_run,
        extract_risk=args.extract_risk,
    )
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
