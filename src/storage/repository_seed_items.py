from __future__ import annotations

from typing import Any, Dict, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.collection.seed_list_parser import normalize_source_item_id
from src.collection.seed_scan_policy import SeedScanPolicy

from .models import (
    CollectionSeedItem,
    CollectionSeedOccurrence,
    CollectionSeedScanJob,
    CollectionSeedScanProgress,
)
from .repository_context import _normalized_seed_text, _utc_now


class RepositorySeedItemsMixin:
    def upsert_seed_items(
        self,
        *,
        job_key: str,
        progress_key: str,
        sort_key: str,
        sort_name: str | None,
        st_param: str,
        page: int,
        source_page_url: str,
        items: Sequence[Dict[str, Any]],
        source_final_url: str | None = None,
        policy: SeedScanPolicy | None = None,
        worker_id: str | None = None,
    ) -> Dict[str, int]:
        if not self.enabled:
            return {
                "seen": 0,
                "new_items": 0,
                "existing_items": 0,
                "new_occurrences": 0,
            }
        self.initialize()
        now = _utc_now()
        seen = 0
        new_items = 0
        existing_items = 0
        new_occurrences = 0
        active_policy = policy or self.adapter.seed_scan_policy
        source_platform = _normalized_seed_text(active_policy.source_platform)
        if not source_platform:
            raise ValueError("seed source platform is required")
        if len(source_platform) > 32:
            raise ValueError("seed source platform must be at most 32 characters")
        with self.session_factory.begin() as session:
            if policy is not None or active_policy.requires_lease_owner:
                job = session.get(CollectionSeedScanJob, job_key)
                progress = session.get(CollectionSeedScanProgress, progress_key)
                if (
                    job is None
                    or progress is None
                    or progress.job_key != job_key
                    or not active_policy.owns_job(job.job_key, job.metadata_json)
                ):
                    raise ValueError(
                        f"seed scan write does not belong to policy: {progress_key}"
                    )
                if active_policy.requires_lease_owner and (
                    progress.status != "in_progress"
                    or progress.leased_by != str(worker_id or "").strip()
                ):
                    raise ValueError(
                        f"seed scan lease is not owned by worker: {progress_key}"
                    )
            dialect_name = session.get_bind().dialect.name
            if dialect_name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as dialect_insert
            elif dialect_name == "sqlite":
                from sqlalchemy.dialects.sqlite import insert as dialect_insert
            for rank, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                raw_source_item_id = _normalized_seed_text(
                    item.get("source_item_id") or item.get("id") or item.get("item_id")
                )
                if not raw_source_item_id:
                    continue
                source_item_id = normalize_source_item_id(raw_source_item_id)
                item_id = active_policy.storage_item_id(source_item_id)
                seen += 1
                url = self._seed_item_url(
                    source_item_id,
                    item.get("url") or item.get("source_url") or item.get("itemUrl"),
                    active_policy,
                )
                title = _normalized_seed_text(
                    item.get("title") or item.get("source_title")
                )
                item_payload = {
                    key: value for key, value in item.items() if not key.startswith("_")
                }
                if raw_source_item_id != source_item_id:
                    item_payload.setdefault("raw_source_item_id", raw_source_item_id)
                item_payload["source_item_id"] = source_item_id
                item_payload["source_platform"] = source_platform
                item_payload.setdefault("url", url)
                item_payload.setdefault("source_url", url)
                seed_item = session.get(CollectionSeedItem, item_id, with_for_update=True)
                if seed_item is None and item_id != source_item_id:
                    seed_item = session.scalars(
                        select(CollectionSeedItem)
                        .where(
                            CollectionSeedItem.source_item_id == source_item_id,
                            CollectionSeedItem.source_platform == source_platform,
                        )
                        .with_for_update()
                    ).first()
                    if seed_item is not None:
                        item_id = seed_item.item_id
                if seed_item is None:
                    insert_values = {
                        "item_id": item_id,
                        "source_item_id": source_item_id,
                        "source_platform": source_platform,
                        "source_url": url,
                        "title": title,
                        "first_seen_job_key": job_key,
                        "first_seen_sort_key": sort_key,
                        "first_seen_at": now,
                        "last_seen_at": now,
                        "source_payload": item_payload,
                        "status": "pending_detail",
                        "detail_attempt_count": 0,
                    }
                    if dialect_name == "postgresql":
                        insert_stmt = dialect_insert(CollectionSeedItem).values(
                            **insert_values
                        )
                        insert_stmt = insert_stmt.on_conflict_do_nothing(
                            index_elements=[CollectionSeedItem.item_id]
                        )
                        insert_stmt = insert_stmt.returning(CollectionSeedItem.item_id)
                    elif dialect_name == "sqlite":
                        insert_stmt = dialect_insert(CollectionSeedItem).values(
                            **insert_values
                        )
                        insert_stmt = insert_stmt.on_conflict_do_nothing(
                            index_elements=[CollectionSeedItem.item_id]
                        )
                    else:
                        insert_stmt = None
                    if insert_stmt is not None:
                        result = session.execute(insert_stmt)
                        # Psycopg may expose rowcount=-1 for INSERT; returned IDs prove insertion.
                        inserted = (
                            result.scalar_one_or_none() is not None
                            if dialect_name == "postgresql"
                            else int(result.rowcount or 0) > 0
                        )
                        if inserted:
                            new_items += 1
                        else:
                            existing_items += 1
                    else:
                        try:
                            with session.begin_nested():
                                session.add(CollectionSeedItem(**insert_values))
                                session.flush()
                            new_items += 1
                        except IntegrityError:
                            existing_items += 1
                    seed_item = session.get(
                        CollectionSeedItem, item_id, with_for_update=True
                    )
                    if seed_item is None:
                        continue
                else:
                    existing_items += 1
                if seed_item.source_platform not in (None, "", source_platform):
                    raise ValueError(
                        f"seed item identity belongs to another source: {item_id}"
                    )
                if seed_item.source_item_id not in (None, "", source_item_id):
                    raise ValueError(
                        f"seed item identity belongs to another source item: {item_id}"
                    )
                if not seed_item.source_platform:
                    seed_item.source_platform = source_platform
                if not seed_item.source_item_id:
                    seed_item.source_item_id = source_item_id
                if not seed_item.source_url and url:
                    seed_item.source_url = url
                if not seed_item.title and title:
                    seed_item.title = title
                seed_item.last_seen_at = now
                seed_item.source_payload = {
                    **(seed_item.source_payload or {}),
                    **item_payload,
                }
                if seed_item.status in (None, "", "blocked"):
                    seed_item.status = "pending_detail"
                session.add(seed_item)

                occurrence_key = self._occurrence_key(
                    item_id=item_id,
                    job_key=job_key,
                    sort_key=sort_key,
                    page=int(page or 1),
                    rank=rank,
                )
                occurrence_values = {
                    "occurrence_key": occurrence_key,
                    "item_id": item_id,
                    "job_key": job_key,
                    "progress_key": progress_key,
                    "sort_key": sort_key,
                    "sort_name": sort_name,
                    "st_param": st_param,
                    "page": int(page or 1),
                    "rank": rank,
                    "source_page_url": source_page_url,
                    "source_final_url": source_final_url,
                    "raw_item": item_payload,
                    "seen_at": now,
                }
                if dialect_name == "postgresql":
                    occurrence_stmt = dialect_insert(CollectionSeedOccurrence).values(
                        **occurrence_values
                    )
                    occurrence_stmt = occurrence_stmt.on_conflict_do_nothing(
                        index_elements=[CollectionSeedOccurrence.occurrence_key]
                    ).returning(CollectionSeedOccurrence.id)
                    occurrence_result = session.execute(occurrence_stmt)
                    if occurrence_result.scalar_one_or_none() is not None:
                        new_occurrences += 1
                elif dialect_name == "sqlite":
                    occurrence_stmt = dialect_insert(CollectionSeedOccurrence).values(
                        **occurrence_values
                    )
                    occurrence_stmt = occurrence_stmt.on_conflict_do_nothing(
                        index_elements=[CollectionSeedOccurrence.occurrence_key]
                    )
                    occurrence_result = session.execute(occurrence_stmt)
                    if int(occurrence_result.rowcount or 0) > 0:
                        new_occurrences += 1
                else:
                    occurrence = session.scalars(
                        select(CollectionSeedOccurrence).where(
                            CollectionSeedOccurrence.occurrence_key == occurrence_key
                        )
                    ).first()
                    if occurrence is None:
                        occurrence = CollectionSeedOccurrence(**occurrence_values)
                        session.add(occurrence)
                        new_occurrences += 1
        return {
            "seen": seen,
            "new_items": new_items,
            "existing_items": existing_items,
            "new_occurrences": new_occurrences,
        }
