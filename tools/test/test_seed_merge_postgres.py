"""Seed/detail serialization against the isolated PostgreSQL test database."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from tools.test.test_quality_postgres_claims import (
    repository as repository,  # noqa: PLC0414
)


def test_seed_merge_preserves_committed_detail_and_parallel_enrichment(repository):
    item_id = uuid4().hex
    seed = {"id": item_id, "title": "seed", "source_title": "seed", "status": "done"}
    repository.upsert_flat_item(seed, "sniff_saved")
    detail = {
        **seed,
        "title": "detail",
        "source_title": "detail",
        "detail_fetch_status": "detail_rejected",
        "is_processed": True,
    }
    repository.upsert_flat_item(detail, "detail_rejected")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                repository.upsert_flat_item, {**seed, key: "evidence"}, "sniff_saved"
            )
            for key in ("extra_a", "extra_b")
        ]
        for future in futures:
            future.result(timeout=15)
    stored = repository.get_flat_item(item_id)
    assert stored["title"] == "detail"
    assert stored["detail_fetch_status"] == "detail_rejected"
    assert stored["extra_a"] == stored["extra_b"] == "evidence"
