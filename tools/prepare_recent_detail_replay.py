#!/usr/bin/env python3
"""为 recent 缺 enrich 且仍保留原始 URL 的记录准备 detail 重抓任务。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.collection.detail_replay import prepare_recent_detail_replay
from src.project_data_paths import resolve_project_data_root
from src.project_environment import getenv as project_getenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="准备 recent detail 重抓任务")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
    )
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-path", type=Path)
    args = parser.parse_args()
    if args.data_root is None:
        args.data_root = Path(
            project_getenv("CROW_DATA_ROOT")
            or resolve_project_data_root(REPO_ROOT) / "datas"
        )
    if args.output_path is None:
        args.output_path = args.data_root / "maintenance" / "recent_detail_replay.json"
    return args


def main() -> None:
    args = parse_args()
    report = prepare_recent_detail_replay(
        data_root=args.data_root,
        window_days=args.window_days,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
