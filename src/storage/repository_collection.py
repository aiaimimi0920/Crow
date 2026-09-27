from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from .canonical_record import CANONICAL_RECORD_SCHEMA_VERSION, build_canonical_payload
from .models import (
    PropertyAudit,
    PropertyIngestEvent,
    PropertyLegalContext,
    PropertyListing,
    PropertyRiskFlags,
)
from .repository_context import _parse_dt, _utc_now


class RepositoryCollectionMixin:
    def _audit_stage_snapshot(self, audit_row: PropertyAudit | None) -> Dict[str, Any]:
        if audit_row is None:
            return {}
        return {
            "seed_status": audit_row.seed_status,
            "seed_first_seen_at": audit_row.seed_first_seen_at,
            "seed_last_seen_at": audit_row.seed_last_seen_at,
            "seed_source_page_url": audit_row.seed_source_page_url,
            "detail_status": audit_row.detail_status,
            "detail_last_error": audit_row.detail_last_error,
            "detail_retry_count": audit_row.detail_retry_count,
            "detail_lease_until": audit_row.detail_lease_until,
            "analysis_status": audit_row.analysis_status,
            "analysis_ready": audit_row.analysis_ready,
            "analysis_missing_fields": audit_row.analysis_missing_fields,
            "analysis_last_scored_at": audit_row.analysis_last_scored_at,
            "analysis_model_version": audit_row.analysis_model_version,
            "detail_fetch_status": audit_row.detail_fetch_status,
        }

    @staticmethod
    def _changed_stage_events(
        existing_stage: Dict[str, Any], stage_state: Dict[str, Any]
    ) -> list[tuple[str, Dict[str, Any]]]:
        events: list[tuple[str, Dict[str, Any]]] = []

        def _append(event_type: str, field: str) -> None:
            previous = existing_stage.get(field)
            current = stage_state.get(field)
            if previous == current or current in (None, "", []):
                return
            events.append(
                (
                    event_type,
                    {
                        "field": field,
                        "previous": previous,
                        "current": current,
                    },
                )
            )

        _append("seed_stage_transition", "seed_status")
        _append("detail_stage_transition", "detail_status")
        _append("analysis_stage_transition", "analysis_status")
        if (
            existing_stage.get("analysis_ready") != stage_state.get("analysis_ready")
            and stage_state.get("analysis_ready") is not None
        ):
            events.append(
                (
                    "analysis_ready_transition",
                    {
                        "field": "analysis_ready",
                        "previous": existing_stage.get("analysis_ready"),
                        "current": stage_state.get("analysis_ready"),
                        "missing_fields": stage_state.get("analysis_missing_fields")
                        or [],
                    },
                )
            )
        return events

    def upsert_collection_record(
        self,
        record: Dict[str, Any],
        event_type: str,
        event_payload: Optional[Dict[str, Any]] = None,
        aux_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        with self.session_factory.begin() as session:
            self._upsert_collection_record_session(
                session,
                record,
                event_type=event_type,
                event_payload=event_payload,
                aux_data=aux_data,
            )

    def _upsert_collection_record_session(
        self,
        session: Session,
        record: Dict[str, Any],
        event_type: str,
        event_payload: Optional[Dict[str, Any]] = None,
        aux_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        source = record["source"]
        archive = record["archive"]
        auction = record["auction"]
        location = record["location"]
        property_section = record["property"]
        legal_context = record["legal_context"]
        risk_flags = record["risk_flags"]
        audit = record["audit"]
        item_id = source["item_id"]
        now = _utc_now()
        listing = session.get(PropertyListing, item_id)
        is_new = listing is None
        if listing is None:
            listing = PropertyListing(item_id=item_id)
        # A normal retry is not an opt-in migration of an existing legacy row.
        if is_new or listing.record_schema_version == CANONICAL_RECORD_SCHEMA_VERSION:
            listing.canonical_payload = build_canonical_payload(
                aux_data or record,
                record,
                previous=listing.canonical_payload,
                captured_at=now,
            )
            listing.record_schema_version = CANONICAL_RECORD_SCHEMA_VERSION
        listing.source_item_id = source.get("source_item_id")
        listing.source_url = source.get("source_url")
        listing.source_title = source.get("source_title")
        listing.source_platform = source.get("source_platform")
        listing.status = auction.get("status")
        listing.auction_date = _parse_dt(auction.get("auction_date"))
        listing.auction_start_time = _parse_dt(auction.get("auction_start_time"))
        listing.auction_round = auction.get("auction_round")
        listing.transaction_price = auction.get("transaction_price")
        listing.starting_price = auction.get("starting_price")
        listing.actual_paid_price = auction.get("actual_paid_price")
        listing.evaluation_price = auction.get("evaluation_price")
        listing.deposit = auction.get("deposit")
        listing.apply_count = auction.get("apply_count")
        listing.bid_count = auction.get("bid_count")
        listing.bidder_count = auction.get("bidder_count")
        listing.watch_count = auction.get("watch_count")
        listing.reminder_count = auction.get("reminder_count")
        listing.view_count = auction.get("view_count")
        listing.full_address = location.get("full_address")
        listing.province = location.get("province")
        listing.city = location.get("city")
        listing.district = location.get("district")
        listing.business_area = location.get("business_area")
        listing.community_name = location.get("community_name")
        listing.latitude = location.get("latitude")
        listing.longitude = location.get("longitude")
        listing.coordinate_source = location.get("coordinate_source")
        listing.housing_type = property_section.get("housing_type")
        listing.area_sqm = property_section.get("area_sqm")
        listing.gross_area_sqm = property_section.get("gross_area_sqm")
        listing.interior_area_sqm = property_section.get("interior_area_sqm")
        listing.land_area_sqm = property_section.get("land_area_sqm")
        listing.ownership_share_ratio = property_section.get("ownership_share_ratio")
        listing.layout = property_section.get("layout")
        listing.build_year = property_section.get("build_year")
        listing.total_floors = property_section.get("total_floors")
        listing.floor_level = property_section.get("floor_level")
        listing.has_elevator = property_section.get("has_elevator")
        listing.orientation = property_section.get("orientation")
        listing.includes_parking = property_section.get("includes_parking")
        listing.special_school_tag = property_section.get("special_school_tag")
        listing.has_keys = property_section.get("has_keys")
        listing.is_deleted = False
        listing.deleted_reason = None
        listing.last_synced_at = now
        session.add(listing)

        risk_row = session.get(PropertyRiskFlags, item_id) or PropertyRiskFlags(
            item_id=item_id
        )
        for key, value in risk_flags.items():
            setattr(risk_row, key, value)
        session.add(risk_row)

        legal_row = session.get(PropertyLegalContext, item_id) or PropertyLegalContext(
            item_id=item_id
        )
        legal_row.court_name = legal_context.get("court_name")
        legal_row.case_number = legal_context.get("case_number")
        legal_row.appraisal_agency_name = legal_context.get("appraisal_agency_name")
        legal_row.appraisal_benchmark_date = _parse_dt(
            legal_context.get("appraisal_benchmark_date")
        )
        legal_row.appraisal_report_urls = (
            legal_context.get("appraisal_report_urls") or []
        )
        legal_row.announcement_attachment_urls = (
            legal_context.get("announcement_attachment_urls") or []
        )
        session.add(legal_row)

        audit_row = session.get(PropertyAudit, item_id) or PropertyAudit(
            item_id=item_id
        )
        existing_stage = self._audit_stage_snapshot(audit_row)
        audit_row.detail_archive_path = source.get("detail_archive_path")
        source_json_path = None
        if isinstance(event_payload, dict):
            source_json_path = (
                event_payload.get("source_file")
                or event_payload.get("json_file")
                or event_payload.get("file_path")
            )
        if source_json_path in ("", None):
            source_json_path = record.get("json_file") or record.get("__file_path")
        if source_json_path not in ("", None):
            audit_row.source_json_path = str(source_json_path)
        audit_row.list_payload_path = archive.get("list_payload_path")
        audit_row.detail_text_path = archive.get("detail_text_path")
        audit_row.component_payload_path = archive.get("component_payload_path")
        audit_row.notice_text_path = archive.get("notice_text_path")
        audit_row.desc_text_path = archive.get("desc_text_path")
        audit_row.attachment_manifest_path = archive.get("attachment_manifest_path")
        audit_row.image_manifest_path = archive.get("image_manifest_path")
        audit_row.extraction_confidence = audit.get("extraction_confidence")
        evidence_span = audit.get("evidence_span")
        audit_row.evidence_span = (
            evidence_span if isinstance(evidence_span, str) else str(evidence_span)
        )
        audit_row.evidence_source = audit.get("evidence_source")
        audit_row.extraction_version = audit.get("extraction_version")
        audit_row.community_name_source = audit.get("community_name_source")
        audit_row.community_name_confidence = audit.get("community_name_confidence")
        audit_row.community_stable_key = audit.get("community_stable_key")
        audit_row.community_raw_name = audit.get("community_raw_name")
        audit_row.beike_community_id = audit.get("beike_community_id")
        audit_row.is_processed = audit.get("is_processed")
        audit_row.detail_captured = audit.get("detail_captured")
        raw_item = aux_data or {}
        audit_row.detail_fetch_status = raw_item.get("detail_fetch_status")
        audit_row.detail_fetch_attempted_at = _parse_dt(
            raw_item.get("detail_fetch_attempted_at")
        )
        audit_row.detail_fetch_attempt_count = raw_item.get(
            "detail_fetch_attempt_count"
        )
        audit_row.detail_fetch_last_url = raw_item.get("detail_fetch_last_url")
        stage_state = self._derive_stage_state(
            record,
            raw_item,
            event_type=event_type,
            existing=existing_stage,
            now=now,
        )
        audit_row.seed_status = stage_state.get("seed_status")
        audit_row.seed_first_seen_at = stage_state.get("seed_first_seen_at")
        audit_row.seed_last_seen_at = stage_state.get("seed_last_seen_at")
        audit_row.seed_source_page_url = stage_state.get("seed_source_page_url")
        audit_row.detail_status = stage_state.get("detail_status")
        audit_row.detail_last_error = stage_state.get("detail_last_error")
        audit_row.detail_retry_count = stage_state.get("detail_retry_count")
        audit_row.detail_lease_until = _parse_dt(stage_state.get("detail_lease_until"))
        if "analysis_status" in stage_state:
            audit_row.analysis_status = stage_state.get("analysis_status")
            audit_row.analysis_ready = stage_state.get("analysis_ready")
            audit_row.analysis_missing_fields = (
                stage_state.get("analysis_missing_fields") or []
            )
            audit_row.analysis_last_scored_at = _parse_dt(
                stage_state.get("analysis_last_scored_at")
            )
            audit_row.analysis_model_version = stage_state.get("analysis_model_version")
        session.add(audit_row)

        for transition_type, transition_payload in self._changed_stage_events(
            existing_stage, stage_state
        ):
            session.add(
                PropertyIngestEvent(
                    item_id=item_id,
                    event_type=transition_type,
                    event_payload=transition_payload,
                )
            )

        event_record = event_payload or {"record": record}
        if not isinstance(event_record, dict):
            event_record = {"payload": event_record}
        session.add(
            PropertyIngestEvent(
                item_id=item_id,
                event_type=event_type,
                event_payload=event_record,
            )
        )
        session.flush()
        self._apply_postgis_point(session, item_id, listing.latitude, listing.longitude)

    def mark_deleted(
        self, item_id: str, reason: str, event_payload: Optional[Dict[str, Any]] = None
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        with self.session_factory.begin() as session:
            listing = session.get(PropertyListing, item_id)
            if listing is None:
                listing = PropertyListing(item_id=item_id)
                session.add(listing)
            listing.is_deleted = True
            listing.deleted_reason = reason
            listing.last_synced_at = _utc_now()
            session.add(
                PropertyIngestEvent(
                    item_id=item_id,
                    event_type="mark_deleted",
                    event_payload=event_payload or {"reason": reason},
                )
            )
