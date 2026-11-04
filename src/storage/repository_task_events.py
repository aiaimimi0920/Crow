from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Sequence

from sqlalchemy import and_, case, func, or_, select

from .models import (
    PropertyAudit,
    PropertyIngestEvent,
    PropertyLegalContext,
    PropertyListing,
    PropertyRiskFlags,
)
from .repository_context import _utc_now


class RepositoryTaskEventsMixin:
    def iter_pending_task_items(self, limit: int = 100) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(
                    PropertyListing.item_id,
                    PropertyListing.source_url,
                    PropertyListing.status,
                )
                .select_from(PropertyListing)
                .outerjoin(
                    PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id
                )
                .where(self._detail_pending_filter())
                .order_by(
                    case((PropertyAudit.detail_status == "failed", 1), else_=0).asc()
                )
                .order_by(
                    PropertyListing.auction_date.asc().nulls_last(),
                    PropertyListing.item_id.asc(),
                )
                .limit(limit)
            )
            rows = session.execute(stmt).all()
            return [
                {
                    "id": str(item_id),
                    "url": source_url,
                    "status": status,
                }
                for item_id, source_url, status in rows
            ]

    def count_pending_task_items(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(func.count())
                .select_from(PropertyListing)
                .outerjoin(
                    PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id
                )
                .where(self._detail_pending_filter())
            )
            return session.scalar(stmt) or 0

    def iter_pending_flat_items(self, limit: int = 100) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        with self.session_factory() as session:
            rows = session.execute(
                select(
                    PropertyListing,
                    PropertyRiskFlags,
                    PropertyLegalContext,
                    PropertyAudit,
                )
                .outerjoin(
                    PropertyRiskFlags,
                    PropertyRiskFlags.item_id == PropertyListing.item_id,
                )
                .outerjoin(
                    PropertyLegalContext,
                    PropertyLegalContext.item_id == PropertyListing.item_id,
                )
                .outerjoin(
                    PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id
                )
                .where(self._detail_pending_filter())
                .order_by(
                    PropertyListing.auction_date.asc().nulls_last(),
                    PropertyListing.item_id.asc(),
                )
                .limit(limit)
            ).all()
            return [
                self._listing_payload_from_rows(listing, risk, legal, audit)
                for listing, risk, legal, audit in rows
            ]

    def iter_archived_detail_candidates(
        self,
        limit: int = 100,
        *,
        require_missing_coordinates: bool = True,
        require_missing_risk: bool = False,
        require_missing_artifacts: bool = True,
    ) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        with self.session_factory() as session:
            conditions = [
                PropertyListing.is_deleted.is_(False),
                PropertyAudit.detail_archive_path.is_not(None),
                PropertyAudit.detail_archive_path != "",
                PropertyAudit.source_json_path.is_not(None),
                PropertyAudit.source_json_path != "",
            ]
            missing_filters = []
            if require_missing_coordinates:
                missing_filters.append(
                    or_(
                        PropertyListing.latitude.is_(None),
                        PropertyListing.longitude.is_(None),
                    )
                )
            if require_missing_risk:
                missing_filters.append(
                    and_(
                        PropertyRiskFlags.is_occupied.is_(None),
                        PropertyRiskFlags.has_long_lease.is_(None),
                        PropertyRiskFlags.clear_delivery.is_(None),
                        PropertyRiskFlags.tax_burden.is_(None),
                        PropertyRiskFlags.is_fractional_share.is_(None),
                    )
                )
            if require_missing_artifacts:
                missing_filters.append(
                    or_(
                        PropertyAudit.detail_text_path.is_(None),
                        PropertyAudit.detail_text_path == "",
                        PropertyAudit.notice_text_path.is_(None),
                        PropertyAudit.notice_text_path == "",
                        PropertyAudit.desc_text_path.is_(None),
                        PropertyAudit.desc_text_path == "",
                        PropertyAudit.component_payload_path.is_(None),
                        PropertyAudit.component_payload_path == "",
                        PropertyAudit.attachment_manifest_path.is_(None),
                        PropertyAudit.attachment_manifest_path == "",
                        PropertyAudit.image_manifest_path.is_(None),
                        PropertyAudit.image_manifest_path == "",
                    )
                )
            if missing_filters:
                conditions.append(or_(*missing_filters))

            rows = session.execute(
                select(
                    PropertyListing,
                    PropertyRiskFlags,
                    PropertyLegalContext,
                    PropertyAudit,
                )
                .outerjoin(
                    PropertyRiskFlags,
                    PropertyRiskFlags.item_id == PropertyListing.item_id,
                )
                .outerjoin(
                    PropertyLegalContext,
                    PropertyLegalContext.item_id == PropertyListing.item_id,
                )
                .outerjoin(
                    PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id
                )
                .where(*conditions)
                .order_by(
                    PropertyListing.auction_date.asc().nulls_last(),
                    PropertyListing.item_id.asc(),
                )
                .limit(limit)
            ).all()
            return [
                self._listing_payload_from_rows(listing, risk, legal, audit)
                for listing, risk, legal, audit in rows
            ]

    def iter_detail_fetch_candidates(self, limit: int = 100) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        done_like_statuses = ("done", "成交", "failure", "failed_timeout")
        blocked_ids = self.recent_event_item_ids(
            ("detail_archive_fetch_blocked", "detail_archive_fetch_failed"),
            hours=24,
        )
        with self.session_factory() as session:
            rows = session.execute(
                select(
                    PropertyListing,
                    PropertyRiskFlags,
                    PropertyLegalContext,
                    PropertyAudit,
                )
                .outerjoin(
                    PropertyRiskFlags,
                    PropertyRiskFlags.item_id == PropertyListing.item_id,
                )
                .outerjoin(
                    PropertyLegalContext,
                    PropertyLegalContext.item_id == PropertyListing.item_id,
                )
                .outerjoin(
                    PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id
                )
                .where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyListing.source_url.is_not(None),
                    PropertyListing.source_url != "",
                    PropertyListing.status.in_(done_like_statuses),
                    PropertyAudit.source_json_path.is_not(None),
                    PropertyAudit.source_json_path != "",
                    or_(
                        PropertyAudit.detail_archive_path.is_(None),
                        PropertyAudit.detail_archive_path == "",
                    ),
                )
                .order_by(
                    PropertyListing.auction_date.asc().nulls_last(),
                    PropertyListing.item_id.asc(),
                )
                .where(PropertyListing.item_id.notin_(blocked_ids))
                .limit(limit)
            ).all()
            return [
                self._listing_payload_from_rows(listing, risk, legal, audit)
                for listing, risk, legal, audit in rows
                if str(listing.item_id) not in blocked_ids
            ][:limit]

    def recent_event_item_ids(self, event_types: Sequence[str], hours: int) -> set[str]:
        if not self.enabled or not event_types:
            return set()
        self.initialize()
        since = _utc_now() - timedelta(hours=max(hours, 0))
        with self.session_factory() as session:
            stmt = (
                select(PropertyIngestEvent.item_id)
                .where(
                    PropertyIngestEvent.item_id.is_not(None),
                    PropertyIngestEvent.event_type.in_(tuple(event_types)),
                    PropertyIngestEvent.created_at >= since,
                )
                .distinct()
            )
            return {str(item_id) for item_id in session.scalars(stmt).all() if item_id}

    def event_type_counts(
        self, event_types: Sequence[str], hours: int | None = None
    ) -> Dict[str, int]:
        counts = {event_type: 0 for event_type in event_types}
        if not self.enabled or not event_types:
            return counts
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(
                    PropertyIngestEvent.event_type, func.count(PropertyIngestEvent.id)
                )
                .where(PropertyIngestEvent.event_type.in_(tuple(event_types)))
                .group_by(PropertyIngestEvent.event_type)
            )
            if hours is not None:
                since = _utc_now() - timedelta(hours=max(hours, 0))
                stmt = stmt.where(PropertyIngestEvent.created_at >= since)
            for event_type, count_value in session.execute(stmt):
                counts[str(event_type)] = int(count_value or 0)
        return counts
