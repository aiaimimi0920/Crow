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

        prepared_entries: list[dict[str, Any]] = []
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
            prepared_entries.append(
                {
                    "rank": rank,
                    "source_item_id": source_item_id,
                    "item_id": item_id,
                    "url": url,
                    "title": title,
                    "item_payload": item_payload,
                }
            )

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
            if not prepared_entries:
                return {
                    "seen": 0,
                    "new_items": 0,
                    "existing_items": 0,
                    "new_occurrences": 0,
                }

            dialect_name = session.get_bind().dialect.name
            dialect_insert = None
            if dialect_name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as dialect_insert
            elif dialect_name == "sqlite":
                from sqlalchemy.dialects.sqlite import insert as dialect_insert

            candidate_ids = sorted({entry["item_id"] for entry in prepared_entries})
            if dialect_name in ("postgresql", "sqlite"):
                locked_by_id: dict[str, CollectionSeedItem] = {
                    row.item_id: row
                    for row in session.scalars(
                        select(CollectionSeedItem)
                        .where(CollectionSeedItem.item_id.in_(candidate_ids))
                        .order_by(CollectionSeedItem.item_id)
                        .with_for_update()
                    ).all()
                }
            else:
                locked_by_id = {}
                for cid in candidate_ids:
                    existing_row = session.get(CollectionSeedItem, cid)
                    if existing_row is not None:
                        locked_by_id[cid] = existing_row

            missing_source_ids = sorted(
                {
                    entry["source_item_id"]
                    for entry in prepared_entries
                    if entry["item_id"] not in locked_by_id
                    and entry["item_id"] != entry["source_item_id"]
                }
            )
            if missing_source_ids:
                by_source: dict[str, CollectionSeedItem] = {}
                for row in session.scalars(
                    select(CollectionSeedItem)
                    .where(
                        CollectionSeedItem.source_platform == source_platform,
                        CollectionSeedItem.source_item_id.in_(missing_source_ids),
                    )
                    .order_by(CollectionSeedItem.item_id)
                    .with_for_update()
                ).all():
                    if row.source_item_id and row.source_item_id not in by_source:
                        by_source[row.source_item_id] = row
                    locked_by_id[row.item_id] = row
                for entry in prepared_entries:
                    if (
                        entry["item_id"] not in locked_by_id
                        and entry["source_item_id"] in by_source
                    ):
                        entry["item_id"] = by_source[entry["source_item_id"]].item_id

            first_insert_by_id: dict[str, dict[str, Any]] = {}
            for entry in prepared_entries:
                target_id = entry["item_id"]
                if target_id in locked_by_id or target_id in first_insert_by_id:
                    continue
                first_insert_by_id[target_id] = {
                    "item_id": target_id,
                    "source_item_id": entry["source_item_id"],
                    "source_platform": source_platform,
                    "source_url": entry["url"],
                    "title": entry["title"],
                    "first_seen_job_key": job_key,
                    "first_seen_sort_key": sort_key,
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "source_payload": entry["item_payload"],
                    "status": "pending_detail",
                    "detail_attempt_count": 0,
                }

            inserted_ids: set[str] = set()
            if first_insert_by_id:
                ordered_inserts = [
                    first_insert_by_id[key] for key in sorted(first_insert_by_id)
                ]
                if dialect_name == "postgresql" and dialect_insert is not None:
                    insert_stmt = (
                        dialect_insert(CollectionSeedItem)
                        .values(ordered_inserts)
                        .on_conflict_do_nothing(
                            index_elements=[CollectionSeedItem.item_id]
                        )
                        .returning(CollectionSeedItem.item_id)
                    )
                    inserted_ids = {
                        str(val) for val in session.execute(insert_stmt).scalars().all()
                    }
                elif dialect_name == "sqlite" and dialect_insert is not None:
                    for values in ordered_inserts:
                        stmt = (
                            dialect_insert(CollectionSeedItem)
                            .values(**values)
                            .on_conflict_do_nothing(
                                index_elements=[CollectionSeedItem.item_id]
                            )
                        )
                        if int(session.execute(stmt).rowcount or 0) > 0:
                            inserted_ids.add(values["item_id"])
                else:
                    for values in ordered_inserts:
                        try:
                            with session.begin_nested():
                                session.add(CollectionSeedItem(**values))
                                session.flush()
                            inserted_ids.add(values["item_id"])
                        except IntegrityError:
                            pass

                for row in session.scalars(
                    select(CollectionSeedItem)
                    .where(CollectionSeedItem.item_id.in_(sorted(first_insert_by_id)))
                    .order_by(CollectionSeedItem.item_id)
                    .with_for_update()
                ).all():
                    locked_by_id[row.item_id] = row

            seen_in_batch: set[str] = set()
            occurrence_batch: list[dict[str, Any]] = []
            seen_occurrence_keys: set[str] = set()
            page_num = int(page or 1)
            for entry in prepared_entries:
                item_id = entry["item_id"]
                source_item_id = entry["source_item_id"]
                url = entry["url"]
                title = entry["title"]
                item_payload = entry["item_payload"]
                if item_id in inserted_ids and item_id not in seen_in_batch:
                    new_items += 1
                else:
                    existing_items += 1
                seen_in_batch.add(item_id)

                seed_item = locked_by_id.get(item_id)
                if seed_item is None:
                    continue
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
                    page=page_num,
                    rank=entry["rank"],
                )
                if occurrence_key in seen_occurrence_keys:
                    continue
                seen_occurrence_keys.add(occurrence_key)
                occurrence_batch.append(
                    {
                        "occurrence_key": occurrence_key,
                        "item_id": item_id,
                        "job_key": job_key,
                        "progress_key": progress_key,
                        "sort_key": sort_key,
                        "sort_name": sort_name,
                        "st_param": st_param,
                        "page": page_num,
                        "rank": entry["rank"],
                        "source_page_url": source_page_url,
                        "source_final_url": source_final_url,
                        "raw_item": item_payload,
                        "seen_at": now,
                    }
                )

            if occurrence_batch:
                if dialect_name == "postgresql" and dialect_insert is not None:
                    occ_stmt = (
                        dialect_insert(CollectionSeedOccurrence)
                        .values(occurrence_batch)
                        .on_conflict_do_nothing(
                            index_elements=[CollectionSeedOccurrence.occurrence_key]
                        )
                        .returning(CollectionSeedOccurrence.id)
                    )
                    new_occurrences += len(session.execute(occ_stmt).scalars().all())
                elif dialect_name == "sqlite" and dialect_insert is not None:
                    occ_stmt = (
                        dialect_insert(CollectionSeedOccurrence)
                        .values(occurrence_batch)
                        .on_conflict_do_nothing(
                            index_elements=[CollectionSeedOccurrence.occurrence_key]
                        )
                    )
                    new_occurrences += max(0, int(session.execute(occ_stmt).rowcount or 0))
                else:
                    existing_occ_keys = set(
                        session.scalars(
                            select(CollectionSeedOccurrence.occurrence_key).where(
                                CollectionSeedOccurrence.occurrence_key.in_(
                                    [row["occurrence_key"] for row in occurrence_batch]
                                )
                            )
                        ).all()
                    )
                    for occ_values in occurrence_batch:
                        if occ_values["occurrence_key"] not in existing_occ_keys:
                            session.add(CollectionSeedOccurrence(**occ_values))
                            new_occurrences += 1

        return {
            "seen": seen,
            "new_items": new_items,
            "existing_items": existing_items,
            "new_occurrences": new_occurrences,
        }
