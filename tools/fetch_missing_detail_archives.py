#!/usr/bin/env python3
"""CLI for the production detail-archive fetch operation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.collection.detail_archive_fetch import fetch_missing_detail_archives


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch missing detail archives and sync JSON + DB"
    )
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--extract-risk", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("datas/avm/fetch_missing_detail_archives.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = fetch_missing_detail_archives(
        data_root=args.data_root,
        limit=args.limit,
        timeout=args.timeout,
        extract_risk=args.extract_risk,
        dry_run=args.dry_run,
    )
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
