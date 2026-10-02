from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional

from sqlalchemy import select

from src.collection.seed_scan_policy import SeedScanPolicy

from .models import CollectionSeedScanJob, CollectionSeedScanProgress
from .repository_context import _cooldown_active, _lease_reclaimable, _utc_now
from .seed_scan_candidates import seed_scan_candidates


class RepositorySeedScanPagesMixin:
    def claim_seed_scan_page(
        self,
        worker_id: str,
        lease_seconds: int = 90,
        *,
        parallel_sorts: bool = False,
        failure_cooldown_threshold: int | None = None,
        failure_cooldown_seconds: int | None = None,
        policy: SeedScanPolicy | None = None,
        breadth_first: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        active_policy = policy or self.adapter.seed_scan_policy
        now = _utc_now()
        lease_until = now + timedelta(seconds=max(lease_seconds, 1))
        cooldown_threshold = max(int(failure_cooldown_threshold or 0), 0)
        cooldown_seconds = max(int(failure_cooldown_seconds or 0), 0)
        failure_cooldown_cutoff = (
            now - timedelta(seconds=cooldown_seconds) if cooldown_seconds > 0 else None
        )

        def failure_in_cooldown(row: CollectionSeedScanProgress) -> bool:
            if cooldown_threshold <= 0 or failure_cooldown_cutoff is None:
                return False
            if not str(row.last_error or "").strip():
                return False
            if int(row.retry_count or 0) < cooldown_threshold:
                return False
            return _cooldown_active(
                row.updated_at, now=now, cutoff=failure_cooldown_cutoff
            )

        with self.session_factory.begin() as session:
            blocked_job_keys: set[str] = set()
            locked_job_keys: set[str] = set()
            ordered = seed_scan_candidates(
                session,
                active_policy,
                parallel_sorts=parallel_sorts,
                blocked_job_keys=blocked_job_keys,
                breadth_first=breadth_first,
            )
            for row, job in ordered:
                if row.job_key in blocked_job_keys:
                    continue
                if row.job_key not in locked_job_keys:
                    # Lock the job before its pages so sequential sorts stay ordered.
                    job = session.scalars(
                        select(CollectionSeedScanJob)
                        .where(CollectionSeedScanJob.job_key == row.job_key)
                        .with_for_update(skip_locked=True)
                        .execution_options(populate_existing=True)
                    ).first()
                    if job is None or not active_policy.owns_job(
                        job.job_key, job.metadata_json
                    ):
                        blocked_job_keys.add(row.job_key)
                        continue
                    locked_job_keys.add(row.job_key)
                else:
                    job = session.get(CollectionSeedScanJob, row.job_key)
                # Refresh only this candidate; a job can have many configured sorts.
                row = session.scalars(
                    select(CollectionSeedScanProgress)
                    .where(CollectionSeedScanProgress.progress_key == row.progress_key)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                ).first()
                if row is None:
                    continue
                if row.status not in {"pending", "in_progress"}:
                    continue
                if row.status == "in_progress" and row.leased_by != worker_id:
                    if not _lease_reclaimable(row.lease_until, now=now):
                        if parallel_sorts:
                            continue
                        blocked_job_keys.add(row.job_key)
                        continue
                if failure_in_cooldown(row):
                    if parallel_sorts:
                        continue
                    blocked_job_keys.add(row.job_key)
                    continue
                if row.max_page is not None and int(row.next_page or 1) > int(
                    row.max_page
                ):
                    row.status = "exhausted"
                    row.leased_by = None
                    row.lease_until = None
                    row.completed_at = row.completed_at or now
                    session.add(row)
                    self._refresh_seed_scan_job_status(session, row.job_key, now)
                    continue

                if not parallel_sorts:
                    earlier_sorts = (
                        select(CollectionSeedScanProgress)
                        .where(
                            CollectionSeedScanProgress.job_key == row.job_key,
                            CollectionSeedScanProgress.sort_order < row.sort_order,
                            CollectionSeedScanProgress.status.in_(
                                ("pending", "in_progress")
                            ),
                        )
                        .order_by(
                            CollectionSeedScanProgress.sort_order,
                            CollectionSeedScanProgress.progress_key,
                        )
                        .with_for_update()
                        .execution_options(populate_existing=True, yield_per=128)
                    )
                    with session.scalars(earlier_sorts) as siblings:
                        blocked = any(
                            not failure_in_cooldown(sibling)
                            and not (
                                sibling.status == "in_progress"
                                and sibling.leased_by != worker_id
                                and _lease_reclaimable(sibling.lease_until, now=now)
                            )
                            for sibling in siblings
                        )
                    if blocked:
                        blocked_job_keys.add(row.job_key)
                        continue

                row.status = "in_progress"
                row.leased_by = worker_id
                row.lease_until = lease_until
                session.add(row)
                self._refresh_seed_scan_job_status(session, row.job_key, now)
                return self._seed_scan_progress_payload(row, job, active_policy)
        return None

    def complete_seed_scan_page(
        self,
        *,
        progress_key: str,
        page: int,
        item_count: int,
        has_next: bool,
        source_url: str | None = None,
        worker_id: str | None = None,
        policy: SeedScanPolicy | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        active_policy = policy or self.adapter.seed_scan_policy
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(CollectionSeedScanProgress, progress_key)
            if row is None:
                if active_policy.requires_lease_owner:
                    raise ValueError(f"unknown seed scan progress: {progress_key}")
                return
            job = session.get(CollectionSeedScanJob, row.job_key)
            normalized_worker = str(worker_id or "").strip()
            if active_policy.requires_lease_owner and (
                job is None
                or not active_policy.owns_job(job.job_key, job.metadata_json)
                or row.leased_by != normalized_worker
            ):
                raise ValueError(
                    f"seed scan lease is not owned by worker: {progress_key}"
                )
            row.last_success_page = max(int(page or 1), int(row.last_success_page or 0))
            row.last_item_count = int(item_count or 0)
            row.last_fetch_url = source_url
            row.last_error = None
            row.retry_count = 0
            row.leased_by = None
            row.lease_until = None
            max_page = int(row.max_page) if row.max_page else None
            next_page = int(page or 1) + 1
            if bool(has_next) and (max_page is None or next_page <= max_page):
                row.status = "pending"
                row.next_page = max(int(row.next_page or 1), next_page)
                row.completed_at = None
            else:
                row.status = "exhausted"
                row.next_page = max(int(row.next_page or 1), int(page or 1))
                row.completed_at = now
            session.add(row)
            self._refresh_seed_scan_job_status(session, row.job_key, now)

    def fail_seed_scan_page(
        self,
        progress_key: str,
        error: str,
        *,
        retryable: bool = True,
        worker_id: str | None = None,
        policy: SeedScanPolicy | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        active_policy = policy or self.adapter.seed_scan_policy
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(CollectionSeedScanProgress, progress_key)
            if row is None:
                if active_policy.requires_lease_owner:
                    raise ValueError(f"unknown seed scan progress: {progress_key}")
                return
            job = session.get(CollectionSeedScanJob, row.job_key)
            normalized_worker = str(worker_id or "").strip()
            if active_policy.requires_lease_owner and (
                job is None
                or not active_policy.owns_job(job.job_key, job.metadata_json)
                or row.leased_by != normalized_worker
            ):
                raise ValueError(
                    f"seed scan lease is not owned by worker: {progress_key}"
                )
            previous_error = str(row.last_error or "").strip()
            row.last_error = str(error)
            if previous_error:
                row.retry_count = int(row.retry_count or 0) + 1
            else:
                row.retry_count = 1
            row.leased_by = None
            row.lease_until = None
            row.status = "pending" if retryable else "blocked"
            row.updated_at = now
            session.add(row)
            self._refresh_seed_scan_job_status(session, row.job_key, now)
