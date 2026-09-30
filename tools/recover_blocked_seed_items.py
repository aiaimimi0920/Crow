"""Operator-controlled blocked queue recovery. Preview first, then apply a bounded batch."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from src.storage.blocked_recovery import requeue_blocked_items
from src.storage.models import CollectionSeedItem
from src.storage.repository import create_repository_from_env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--after-id", default="")
    parser.add_argument("--item-id", action="append")
    parser.add_argument("--max-rounds", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("limit must be in 1..100")
    repository = create_repository_from_env()
    if not repository.enabled:
        parser.error("an enabled database is required")
    repository.initialize()
    ids = args.item_id
    if not ids:
        with repository.session_factory() as session:
            ids = list(session.scalars(
                select(CollectionSeedItem.item_id)
                .where(CollectionSeedItem.status.in_(("analysis_blocked", "detail_blocked")),
                       CollectionSeedItem.item_id > args.after_id)
                .order_by(CollectionSeedItem.item_id)
                .limit(args.limit)
            ))
    results = requeue_blocked_items(repository, ids, recovery_id=args.recovery_id,
                                   apply=args.apply, max_rounds=args.max_rounds)
    counts = Counter(str(result.get("skip") or result.get("target_status")) for result in results)
    print(json.dumps({"apply": args.apply, "recovery_id": args.recovery_id,
                      "next_after_id": max(ids) if ids else None,
                      "counts": dict(counts), "results": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
