from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, Sequence
from urllib.parse import urlsplit

from sqlalchemy import not_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.collection.seed_scan_policy import (
    DEFAULT_SEED_SCAN_POLICY,
    GenericSeedScanPolicy,
    SeedScanPolicy,
    TaobaoJudicialSeedScanPolicy,
)

from .models import FapaiSeedScanJob, FapaiSeedScanProgress
from .repository_context import _normalized_seed_text, _utc_now
from .seed_scan_job_status import apply_job_status, refresh_job_statuses

SEED_SCAN_MAINTENANCE_BATCH_SIZE = 128
_TAOBAO_SOURCE_PLATFORMS = frozenset({"taobao", "taobao_judicial", "taobao_sf", "sf.taobao.com"})


class RepositorySeedScanJobsMixin:
    @staticmethod
    def _seed_scan_job_key(job: Dict[str, Any]) -> str:
        explicit = _normalized_seed_text(job.get("job_key"))
        if explicit:
            return explicit
        location_code = _normalized_seed_text(job.get("location_code")) or "unknown-location"
        category = _normalized_seed_text(job.get("category")) or "unknown-category"
        district = _normalized_seed_text(job.get("district")) or _normalized_seed_text(job.get("city")) or "scope"
        return f"{location_code}:{category}:{district}"

    @staticmethod
    def _seed_scan_progress_key(job_key: str, sort_key: str) -> str:
        raw = f"{job_key}:{sort_key}"
        if len(raw) <= 256:
            return raw
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
        return f"{job_key[:210]}:{digest}"

    @staticmethod
    def _occurrence_key(
        *,
        item_id: str,
        job_key: str,
        sort_key: str,
        page: int,
        rank: int,
    ) -> str:
        raw = f"{item_id}|{job_key}|{sort_key}|{page}|{rank}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _seed_item_url(
        item_id: str,
        explicit_url: Any = None,
        policy: SeedScanPolicy | None = None,
    ) -> str:
        return (policy or DEFAULT_SEED_SCAN_POLICY).item_url(item_id, explicit_url)

    @staticmethod
    def _seed_item_policy(
        *,
        source_platform: Any = None,
        explicit_url: Any = None,
        policy: SeedScanPolicy | None = None,
    ) -> SeedScanPolicy:
        """Resolve detail URL semantics without fabricating Taobao URLs for generic rows."""
        if policy is not None:
            return policy
        platform = _normalized_seed_text(source_platform)
        if platform:
            if platform.lower() in _TAOBAO_SOURCE_PLATFORMS:
                return TaobaoJudicialSeedScanPolicy()
            return GenericSeedScanPolicy(source_platform=platform)
        url = _normalized_seed_text(explicit_url)
        if url:
            candidate = f"https:{url}" if url.startswith("//") else url
            try:
                hostname = (urlsplit(candidate).hostname or "").lower()
            except ValueError:
                hostname = ""
            if hostname == "taobao.com" or hostname.endswith(".taobao.com"):
                return TaobaoJudicialSeedScanPolicy()
            return GenericSeedScanPolicy()
        # Rows created before source_platform existed retain the legacy fallback.
        return DEFAULT_SEED_SCAN_POLICY

    @staticmethod
    def _seed_scan_progress_payload(
        row: FapaiSeedScanProgress,
        job: FapaiSeedScanJob,
        policy: SeedScanPolicy | None = None,
    ) -> Dict[str, Any]:
        active_policy = policy or DEFAULT_SEED_SCAN_POLICY
        page = int(row.next_page or 1)
        url = active_policy.build_page_url(
            source_url_template=job.source_url_template,
            location_code=job.location_code,
            category=job.category,
            sort_key=row.sort_key,
            st_param=row.st_param,
            page=page,
        )
        return {
            "job_key": row.job_key,
            "progress_key": row.progress_key,
            "source_platform": active_policy.source_platform,
            "province": job.province,
            "city": job.city,
            "district": job.district,
            "location_code": job.location_code,
            "category": job.category,
            "sort_key": row.sort_key,
            "sort_name": row.sort_name,
            "st_param": row.st_param,
            "sort_order": row.sort_order,
            "page": page,
            "max_page": row.max_page,
            "url": url,
        }

    @staticmethod
    def _seed_category_order(
        category: str | None,
        policy: SeedScanPolicy | None = None,
    ) -> tuple[int, str]:
        return (policy or DEFAULT_SEED_SCAN_POLICY).category_order(category)

    @staticmethod
    def _seed_scan_scope_order_key(
        job: FapaiSeedScanJob | None,
        policy: SeedScanPolicy | None = None,
    ) -> tuple[Any, ...]:
        if job is None:
            return ("", "", "", "", 10_000, "", "")
        category_rank, category = RepositorySeedScanJobsMixin._seed_category_order(job.category, policy)
        return (
            _normalized_seed_text(job.province),
            _normalized_seed_text(job.city),
            _normalized_seed_text(job.district),
            _normalized_seed_text(job.location_code),
            category_rank,
            category,
            _normalized_seed_text(job.job_key),
        )

    def _refresh_seed_scan_job_status(
        self, session: Session, job_key: str, now: datetime | None = None
    ) -> None:
        now = now or _utc_now()
        job = session.get(FapaiSeedScanJob, job_key)
        if job is None:
            return
        statuses = set(
            session.scalars(
                select(FapaiSeedScanProgress.status)
                .where(FapaiSeedScanProgress.job_key == job_key)
                .distinct()
            )
        )
        apply_job_status(session, job, statuses, now)

    def ensure_seed_scan_job(
        self,
        job: Dict[str, Any],
        *,
        sort_specs: Sequence[Dict[str, Any]],
        max_page: int | None = None,
        policy: SeedScanPolicy | None = None,
    ) -> Dict[str, Any]:
        active_policy = policy or DEFAULT_SEED_SCAN_POLICY
        if not self.enabled:
            job_key = (
                active_policy.normalize_job(job).job_key
                if policy is not None
                else self._seed_scan_job_key(job)
            )
            return {"job_key": job_key, "created": False, "progress_created": 0}
        self.initialize()
        normalized_job = active_policy.normalize_job(job)
        job_key = normalized_job.job_key
        if not sort_specs:
            raise ValueError("seed scan job requires at least one sort spec")

        now = _utc_now()
        progress_created = 0

        def apply_job_fields(row: FapaiSeedScanJob) -> None:
            row.province = normalized_job.province
            row.city = normalized_job.city
            row.district = normalized_job.district
            row.location_code = normalized_job.location_code
            row.category = normalized_job.category
            if row.status in (None, ""):
                row.status = "pending"
                row.completed_at = None
            row.source_url_template = normalized_job.source_url_template
            row.metadata_json = normalized_job.metadata

        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedScanJob, job_key)
            if row is None:
                row = FapaiSeedScanJob(job_key=job_key)
                apply_job_fields(row)
                try:
                    with session.begin_nested():
                        session.add(row)
                        session.flush()
                    created = True
                except IntegrityError:
                    created = False
                    row = session.get(FapaiSeedScanJob, job_key)
                    if row is None:
                        raise
            else:
                created = False
            apply_job_fields(row)
            session.add(row)

            for index, sort_spec in enumerate(sort_specs):
                sort_key = _normalized_seed_text(sort_spec.get("sort_key")) or _normalized_seed_text(sort_spec.get("st_param")) or f"sort_{index}"
                st_param = _normalized_seed_text(sort_spec.get("st_param")) or sort_key
                progress_key = self._seed_scan_progress_key(job_key, sort_key)
                progress = session.get(FapaiSeedScanProgress, progress_key)
                if progress is None:
                    progress = FapaiSeedScanProgress(
                        progress_key=progress_key,
                        job_key=job_key,
                        sort_key=sort_key,
                        st_param=st_param,
                        next_page=1,
                        status="pending",
                        retry_count=0,
                    )
                    try:
                        with session.begin_nested():
                            session.add(progress)
                            session.flush()
                        progress_created += 1
                    except IntegrityError:
                        progress = session.get(FapaiSeedScanProgress, progress_key)
                        if progress is None:
                            progress = session.scalar(
                                select(FapaiSeedScanProgress).where(
                                    FapaiSeedScanProgress.job_key == job_key,
                                    FapaiSeedScanProgress.sort_key == sort_key,
                                )
                            )
                        if progress is None:
                            raise
                progress.sort_name = _normalized_seed_text(sort_spec.get("sort_name")) or sort_key
                progress.st_param = st_param
                progress.sort_order = int(sort_spec.get("sort_order") if sort_spec.get("sort_order") is not None else index)
                progress.max_page = int(max_page) if max_page else None
                if progress.status in (None, "", "archived"):
                    progress.status = "pending"
                    progress.completed_at = None
                session.add(progress)

            self._refresh_seed_scan_job_status(session, job_key, now)
        return {"job_key": job_key, "created": created, "progress_created": progress_created}

    def archive_seed_scan_jobs_except(
        self,
        active_job_keys: Sequence[str],
        *,
        policy: SeedScanPolicy | None = None,
    ) -> Dict[str, int]:
        active_policy = policy or DEFAULT_SEED_SCAN_POLICY
        normalized_keys = sorted(
            {
                active_policy.normalize_job_key(key)
                for key in (_normalized_seed_text(value) for value in active_job_keys)
                if key
            }
        )
        if not self.enabled:
            return {
                "active_job_count": len(normalized_keys),
                "archived_jobs": 0,
                "archived_progress": 0,
            }
        if not normalized_keys:
            raise ValueError("active_job_keys must not be empty")
        self.initialize()
        now = _utc_now()
        archived_jobs = 0
        archived_progress = 0
        with self.session_factory.begin() as session:
            last_job_key: str | None = None
            while True:
                job_query = select(FapaiSeedScanJob).where(
                    not_(FapaiSeedScanJob.job_key.in_(normalized_keys))
                )
                if last_job_key is not None:
                    job_query = job_query.where(FapaiSeedScanJob.job_key > last_job_key)
                stale_jobs = session.scalars(
                    job_query.order_by(FapaiSeedScanJob.job_key).limit(
                        SEED_SCAN_MAINTENANCE_BATCH_SIZE
                    )
                ).all()
                if not stale_jobs:
                    break
                last_job_key = stale_jobs[-1].job_key
                owned_stale_jobs = [
                    row
                    for row in stale_jobs
                    if active_policy.owns_job(row.job_key, row.metadata_json)
                ]
                stale_job_keys = [row.job_key for row in owned_stale_jobs]

                for row in owned_stale_jobs:
                    if row.status != "archived":
                        archived_jobs += 1
                    row.status = "archived"
                    row.updated_at = now
                    session.add(row)
                session.flush()

                last_progress_key: str | None = None
                while stale_job_keys:
                    progress_query = select(FapaiSeedScanProgress).where(
                        FapaiSeedScanProgress.job_key.in_(stale_job_keys)
                    )
                    if last_progress_key is not None:
                        progress_query = progress_query.where(
                            FapaiSeedScanProgress.progress_key > last_progress_key
                        )
                    stale_progress_rows = session.scalars(
                        progress_query.order_by(
                            FapaiSeedScanProgress.progress_key
                        ).limit(SEED_SCAN_MAINTENANCE_BATCH_SIZE)
                    ).all()
                    if not stale_progress_rows:
                        break
                    last_progress_key = stale_progress_rows[-1].progress_key
                    for row in stale_progress_rows:
                        if row.status != "archived":
                            archived_progress += 1
                        row.status = "archived"
                        row.leased_by = None
                        row.lease_until = None
                        row.updated_at = now
                        session.add(row)
                    session.flush()

                # Release references from each bounded window before loading the
                # next one. The enclosing transaction remains atomic.
                session.expunge_all()
        return {
            "active_job_count": len(normalized_keys),
            "archived_jobs": archived_jobs,
            "archived_progress": archived_progress,
        }

    def release_seed_scan_worker_leases(self, worker_id: str) -> Dict[str, int]:
        if not self.enabled:
            return {"released": 0}
        normalized_worker_id = str(worker_id or "").strip()
        if not normalized_worker_id:
            return {"released": 0}
        self.initialize()
        now = _utc_now()
        released = 0
        with self.session_factory.begin() as session:
            while True:
                rows = session.scalars(
                    select(FapaiSeedScanProgress)
                    .where(
                        FapaiSeedScanProgress.status == "in_progress",
                        FapaiSeedScanProgress.leased_by == normalized_worker_id,
                    )
                    .order_by(FapaiSeedScanProgress.progress_key)
                    .limit(SEED_SCAN_MAINTENANCE_BATCH_SIZE)
                ).all()
                if not rows:
                    break

                job_keys = {row.job_key for row in rows}
                for row in rows:
                    row.status = "pending"
                    row.leased_by = None
                    row.lease_until = None
                    row.updated_at = now
                    session.add(row)
                session.flush()
                refresh_job_statuses(session, job_keys, now)
                session.flush()
                released += len(rows)
                # Do not retain ORM rows from a completed batch in a long-lived
                # worker session while the next window is loaded.
                session.expunge_all()
        return {"released": released}
