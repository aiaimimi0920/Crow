from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional, Sequence

from sqlalchemy import case, func, literal, or_, select

from src.collection.search_task_policy import SearchTaskPolicy

from .models import PropertySearchTask
from .repository_context import _lease_reclaimable, _parse_dt, _utc_now


class RepositorySearchMixin:
    @staticmethod
    def _search_task_key(location_code: str, category: str, sort_param: str) -> str:
        return f"{location_code}:{category}:{sort_param}"

    def bootstrap_search_task(
        self,
        task: Dict[str, Any],
        leased_by: str | None = None,
        lease_seconds: int = 90,
        *,
        policy: SearchTaskPolicy | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        self.initialize()
        active_policy = policy or self.adapter.search_task_policy
        seed = active_policy.normalize_bootstrap(task)
        if seed is None:
            return False
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(PropertySearchTask, seed.task_key) or PropertySearchTask(
                task_key=seed.task_key
            )
            row.location_code = seed.location_code
            row.category = seed.category
            row.sort_param = seed.sort_param
            row.next_page = seed.page
            row.source_url = seed.source_url
            row.last_seen_at = now
            if leased_by:
                row.leased_by = leased_by
                row.lease_until = now + timedelta(seconds=max(lease_seconds, 1))
                row.status = "in_progress"
            else:
                row.status = row.status or "pending"
            session.add(row)
        return True

    def claim_search_task(
        self,
        session_id: str,
        lease_seconds: int = 90,
        *,
        priority_codes: Sequence[str] | None = None,
        sort_order: Sequence[str] | None = None,
        policy: SearchTaskPolicy | None = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        active_policy = policy or self.adapter.search_task_policy
        now = _utc_now()
        priority_index = {code: idx for idx, code in enumerate(priority_codes or [])}
        sort_index = {
            code: idx
            for idx, code in enumerate(sort_order or ("2", "1", "0", "3", "4", "5"))
        }
        with self.session_factory.begin() as session:
            # Stream candidate keys without locking unrelated work. Each actual
            # claim below locks and refreshes only its selected row.
            pending_order = case((PropertySearchTask.status == "pending", 0), else_=1)
            location_order = (
                case(
                    *[
                        (PropertySearchTask.location_code == code, index)
                        for code, index in priority_index.items()
                    ],
                    else_=10**9,
                )
                if priority_index
                else literal(10**9)
            )
            sort_order_expr = case(
                *[
                    (PropertySearchTask.sort_param == code, index)
                    for code, index in sort_index.items()
                ],
                else_=10**9,
            )
            available = or_(
                PropertySearchTask.status == "pending",
                PropertySearchTask.leased_by == session_id,
                PropertySearchTask.lease_until.is_(None),
                PropertySearchTask.lease_until <= now,
            )
            candidates = session.scalars(
                select(PropertySearchTask.task_key)
                .where(
                    PropertySearchTask.status.in_(("pending", "in_progress")), available
                )
                .order_by(
                    pending_order,
                    location_order,
                    sort_order_expr,
                    # Python's previous ``row.updated_at or datetime.min`` put
                    # missing timestamps first; preserve that ordering here.
                    PropertySearchTask.updated_at.asc().nulls_first(),
                    PropertySearchTask.task_key,
                )
                .execution_options(yield_per=128)
            )
            with candidates:
                for task_key in candidates:
                    if not active_policy.owns_task(str(task_key)):
                        continue
                    row = session.scalar(
                        select(PropertySearchTask)
                        .where(PropertySearchTask.task_key == task_key, available)
                        .with_for_update(skip_locked=True)
                        .execution_options(populate_existing=True)
                    )
                    if row is None or row.status not in {"pending", "in_progress"}:
                        continue
                    if row.status == "in_progress" and row.leased_by != session_id:
                        if not _lease_reclaimable(row.lease_until, now=now):
                            continue
                    row.status = "in_progress"
                    row.leased_by = session_id
                    row.lease_until = now + timedelta(seconds=max(lease_seconds, 1))
                    row.last_seen_at = now
                    session.add(row)
                    page = int(row.next_page or 1)
                    return active_policy.claim_payload(
                        task_key=str(row.task_key),
                        location_code=str(row.location_code),
                        category=str(row.category or ""),
                        sort_param=str(row.sort_param or ""),
                        page=page,
                        source_url=row.source_url,
                    )
        return None

    def report_search_task_progress(
        self,
        *,
        url: str | None = None,
        page_num: int,
        has_next: bool = True,
        max_page: int | None = None,
        zero_bid_detected: bool = False,
        task_key: str | None = None,
        next_url: str | None = None,
        session_id: str | None = None,
        policy: SearchTaskPolicy | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        active_policy = policy or self.adapter.search_task_policy
        resolved_key = active_policy.resolve_progress_task_key(
            task_key=task_key, url=url
        )
        if not resolved_key:
            if active_policy.requires_lease_owner:
                raise ValueError("source-scoped search progress requires task_key")
            return

        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(PropertySearchTask, resolved_key)
            if row is None:
                seed = active_policy.normalize_bootstrap({"url": url, "page": page_num})
                if seed is None or seed.task_key != resolved_key:
                    raise ValueError(f"unknown search task: {resolved_key}")
                row = PropertySearchTask(task_key=resolved_key)
                row.location_code = seed.location_code
                row.category = seed.category
                row.sort_param = seed.sort_param
                row.next_page = seed.page

            normalized_session = str(session_id or "").strip()
            if (
                active_policy.requires_lease_owner
                and row.leased_by != normalized_session
            ):
                raise ValueError(
                    f"search task lease is not owned by session: {resolved_key}"
                )
            if normalized_session and row.leased_by not in (None, normalized_session):
                raise ValueError(
                    f"search task lease is owned by another session: {resolved_key}"
                )

            decision = active_policy.progress_decision(
                sort_param=str(row.sort_param or ""),
                current_next_page=int(row.next_page or 1),
                current_source_url=row.source_url,
                page_num=page_num,
                has_next=has_next,
                zero_bid_detected=zero_bid_detected,
                url=url,
                next_url=next_url,
            )
            row.source_url = decision.source_url
            row.last_seen_at = now
            if max_page and (row.max_page is None or max_page > row.max_page):
                row.max_page = max_page
            row.status = decision.status
            row.next_page = decision.next_page
            if decision.zero_bid_terminated is not None:
                row.zero_bid_terminated = decision.zero_bid_terminated
            row.leased_by = None
            row.lease_until = None
            session.add(row)
            if decision.sibling_status in {"pending", "pruned"}:
                for sibling_sort in active_policy.sibling_sort_params:
                    sibling_key = self._search_task_key(
                        row.location_code, row.category or "", sibling_sort
                    )
                    sibling = session.get(
                        PropertySearchTask, sibling_key
                    ) or PropertySearchTask(task_key=sibling_key)
                    sibling.location_code = row.location_code
                    sibling.category = row.category
                    sibling.sort_param = sibling_sort
                    sibling.next_page = max(int(sibling.next_page or 1), 1)
                    sibling.source_url = active_policy.sibling_url(
                        location_code=row.location_code,
                        category=row.category or "",
                        sort_param=sibling_sort,
                        page=sibling.next_page,
                    )
                    sibling.status = decision.sibling_status
                    sibling.zero_bid_terminated = decision.sibling_status == "pruned"
                    sibling.leased_by = None
                    sibling.lease_until = None
                    sibling.last_seen_at = now
                    session.add(sibling)

    def search_task_counts(self) -> Dict[str, int]:
        counts = {
            "search_pending": 0,
            "search_in_progress": 0,
            "search_done": 0,
            "search_pruned": 0,
        }
        if not self.enabled:
            return counts
        self.initialize()
        with self.session_factory() as session:
            stmt = select(
                PropertySearchTask.status, func.count(PropertySearchTask.task_key)
            ).group_by(PropertySearchTask.status)
            for status, count_value in session.execute(stmt):
                key = f"search_{status}"
                if key in counts:
                    counts[key] = int(count_value or 0)
        return counts

    def count_search_tasks(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            return int(
                session.scalar(select(func.count()).select_from(PropertySearchTask))
                or 0
            )

    def ensure_seed_search_tasks(
        self,
        location_codes: Sequence[str],
        categories: Sequence[str],
        sort_param: str = "2",
    ) -> int:
        """Bootstrap legacy Taobao search rows; generic sources use bootstrap_search_task."""
        if not self.enabled:
            return 0
        self.initialize()
        inserted = 0
        with self.session_factory.begin() as session:
            for location_code in location_codes:
                if not location_code:
                    continue
                for category in categories:
                    task_key = self._search_task_key(
                        str(location_code), str(category), str(sort_param)
                    )
                    row = session.get(PropertySearchTask, task_key)
                    if row is not None:
                        continue
                    row = PropertySearchTask(
                        task_key=task_key,
                        location_code=str(location_code),
                        category=str(category),
                        sort_param=str(sort_param),
                        next_page=1,
                        status="pending",
                        zero_bid_terminated=False,
                        retry_count=0,
                        source_url=self._build_search_task_url(
                            str(location_code), str(category), str(sort_param), 1
                        ),
                    )
                    session.add(row)
                    inserted += 1
        return inserted

    def import_search_task_snapshots(self, snapshots: Sequence[Dict[str, Any]]) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        imported = 0
        with self.session_factory.begin() as session:
            for snapshot in snapshots:
                location_code = str(snapshot.get("location_code") or "").strip()
                category = str(snapshot.get("category") or "").strip()
                sort_param = str(snapshot.get("sort_param") or "").strip()
                if not location_code or not category or not sort_param:
                    continue
                task_key = self._search_task_key(location_code, category, sort_param)
                row = session.get(PropertySearchTask, task_key) or PropertySearchTask(
                    task_key=task_key
                )
                pages = snapshot.get("pages") or []
                page_floor = max(
                    [int(p) for p in pages if isinstance(p, int) or str(p).isdigit()]
                    or [0]
                )
                dispatched_page = int(snapshot.get("dispatched_page") or 0)
                next_page = (
                    max(page_floor, dispatched_page, 0) + 1
                    if not snapshot.get("is_done")
                    else max(page_floor, dispatched_page, 1)
                )
                last_update = _parse_dt(snapshot.get("last_update_time"))
                need_try = bool(snapshot.get("need_try", True))
                is_done = bool(snapshot.get("is_done", False))
                max_page = snapshot.get("max_page")
                max_page_int = (
                    int(max_page)
                    if max_page not in (None, "")
                    and str(max_page).lstrip("-").isdigit()
                    else None
                )

                status = "pending"
                zero_bid_terminated = False
                if is_done and not need_try and sort_param != "2":
                    status = "pruned"
                elif is_done:
                    status = "done"
                    if (
                        sort_param == "2"
                        and max_page_int is not None
                        and 0 < max_page_int < 83
                    ):
                        zero_bid_terminated = True
                elif snapshot.get("now_session_id"):
                    status = "in_progress"

                row.location_code = location_code
                row.category = category
                row.sort_param = sort_param
                row.next_page = max(next_page, 1)
                row.max_page = max_page_int
                row.status = status
                row.leased_by = (
                    str(snapshot.get("now_session_id") or "").strip() or None
                )
                row.lease_until = (
                    last_update + timedelta(seconds=90)
                    if row.leased_by and last_update
                    else None
                )
                row.zero_bid_terminated = zero_bid_terminated
                row.source_url = self._build_search_task_url(
                    location_code, category, sort_param, row.next_page
                )
                row.last_seen_at = last_update
                row.retry_count = int(row.retry_count or 0)
                session.add(row)
                imported += 1
        return imported
