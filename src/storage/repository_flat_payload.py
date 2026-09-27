from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Iterable, Optional

from .canonical_record import merge_canonical_payload_into_flat
from .models import (
    PropertyAudit,
    PropertyLegalContext,
    PropertyListing,
    PropertyRiskFlags,
)
from .repository_context import _coerce_naive_utc


class RepositoryFlatPayloadMixin:
    def upsert_flat_item(
        self,
        item: Dict[str, Any],
        event_type: str,
        event_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        record = self._build_collection_record(item)
        self.upsert_collection_record(
            record, event_type=event_type, event_payload=event_payload, aux_data=item
        )

    def upsert_flat_items(
        self,
        items: Iterable[Dict[str, Any]],
        event_type: str,
        event_payload_factory: Optional[
            Callable[[Dict[str, Any], int], Optional[Dict[str, Any]]]
        ] = None,
    ) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        record_pairs = [
            (self._build_collection_record(item), item)
            for item in items
            if isinstance(item, dict)
        ]
        records = [record for record, _item in record_pairs]
        if not records:
            return 0

        with self.session_factory.begin() as session:
            for index, (record, original_item) in enumerate(record_pairs):
                payload = (
                    event_payload_factory(record, index)
                    if event_payload_factory
                    else None
                )
                self._upsert_collection_record_session(
                    session,
                    record,
                    event_type=event_type,
                    event_payload=payload,
                    aux_data=original_item,
                )
        return len(records)

    @staticmethod
    def _fmt_dt(value: Optional[datetime]) -> Optional[str]:
        value = _coerce_naive_utc(value)
        if value is None:
            return None
        return value.strftime("%Y-%m-%d %H:%M:%S")

    def _listing_payload_from_rows(
        self,
        listing: PropertyListing,
        risk: PropertyRiskFlags | None,
        legal: PropertyLegalContext | None,
        audit: PropertyAudit | None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": listing.item_id,
            "item_id": listing.item_id,
            "source_item_id": listing.source_item_id,
            "title": listing.source_title,
            "source_title": listing.source_title,
            "url": listing.source_url,
            "source_url": listing.source_url,
            "source_platform": listing.source_platform,
            "status": listing.status,
            "auction_date": self._fmt_dt(listing.auction_date),
            "交易时间": self._fmt_dt(listing.auction_date),
            "auction_start_time": self._fmt_dt(listing.auction_start_time),
            "开拍时间": self._fmt_dt(listing.auction_start_time),
            "auction_round": listing.auction_round,
            "transaction_price": float(listing.transaction_price)
            if listing.transaction_price is not None
            else None,
            "成交价格": float(listing.transaction_price)
            if listing.transaction_price is not None
            else None,
            "starting_price": float(listing.starting_price)
            if listing.starting_price is not None
            else None,
            "起拍价格": float(listing.starting_price)
            if listing.starting_price is not None
            else None,
            "actual_paid_price": float(listing.actual_paid_price)
            if listing.actual_paid_price is not None
            else None,
            "evaluation_price": float(listing.evaluation_price)
            if listing.evaluation_price is not None
            else None,
            "市场评估价": float(listing.evaluation_price)
            if listing.evaluation_price is not None
            else None,
            "deposit": float(listing.deposit) if listing.deposit is not None else None,
            "保证金": float(listing.deposit) if listing.deposit is not None else None,
            "apply_count": listing.apply_count,
            "竞拍人数": listing.apply_count,
            "bid_count": listing.bid_count,
            "出价次数": listing.bid_count,
            "bidder_count": listing.bidder_count,
            "出价人数": listing.bidder_count,
            "watch_count": listing.watch_count,
            "reminder_count": listing.reminder_count,
            "view_count": listing.view_count,
            "full_address": listing.full_address,
            "完整地址": listing.full_address,
            "地点": listing.full_address,
            "province": listing.province,
            "省份": listing.province,
            "city": listing.city,
            "城市": listing.city,
            "district": listing.district,
            "区": listing.district,
            "business_area": listing.business_area,
            "最靠近商圈": listing.business_area,
            "community_name": listing.community_name,
            "所属小区": listing.community_name,
            "latitude": listing.latitude,
            "纬度": listing.latitude,
            "longitude": listing.longitude,
            "经度": listing.longitude,
            "coordinate_source": listing.coordinate_source,
            "housing_type": listing.housing_type,
            "area_sqm": float(listing.area_sqm)
            if listing.area_sqm is not None
            else None,
            "建筑面积": float(listing.area_sqm)
            if listing.area_sqm is not None
            else None,
            "gross_area_sqm": float(listing.gross_area_sqm)
            if listing.gross_area_sqm is not None
            else None,
            "产权建筑面积": float(listing.gross_area_sqm)
            if listing.gross_area_sqm is not None
            else None,
            "interior_area_sqm": float(listing.interior_area_sqm)
            if listing.interior_area_sqm is not None
            else None,
            "land_area_sqm": float(listing.land_area_sqm)
            if listing.land_area_sqm is not None
            else None,
            "ownership_share_ratio": float(listing.ownership_share_ratio)
            if listing.ownership_share_ratio is not None
            else None,
            "产权份额比例": float(listing.ownership_share_ratio)
            if listing.ownership_share_ratio is not None
            else None,
            "layout": listing.layout,
            "build_year": listing.build_year,
            "total_floors": listing.total_floors,
            "floor_level": listing.floor_level,
            "has_elevator": listing.has_elevator,
            "orientation": listing.orientation,
            "includes_parking": listing.includes_parking,
            "special_school_tag": listing.special_school_tag,
            "has_keys": listing.has_keys,
        }

        risk_payload = {
            "land_right_type": risk.land_right_type if risk else None,
            "is_occupied": risk.is_occupied if risk else None,
            "has_long_lease": risk.has_long_lease if risk else None,
            "clear_delivery": risk.clear_delivery if risk else None,
            "tax_burden": risk.tax_burden if risk else None,
            "property_fee_owed": risk.property_fee_owed if risk else None,
            "is_restricted_purchase": risk.is_restricted_purchase if risk else None,
            "is_fractional_share": risk.is_fractional_share if risk else None,
            "tax_is_company_owned": risk.tax_is_company_owned if risk else None,
            "is_haunted": risk.is_haunted if risk else None,
            "has_lease_before_mortgage": risk.has_lease_before_mortgage
            if risk
            else None,
        }
        legal_payload = {
            "court_name": legal.court_name if legal else None,
            "法院名称": legal.court_name if legal else None,
            "case_number": legal.case_number if legal else None,
            "案号": legal.case_number if legal else None,
            "appraisal_agency_name": legal.appraisal_agency_name if legal else None,
            "appraisal_benchmark_date": self._fmt_dt(legal.appraisal_benchmark_date)
            if legal
            else None,
            "appraisal_report_urls": legal.appraisal_report_urls
            if legal and legal.appraisal_report_urls
            else [],
            "announcement_attachment_urls": legal.announcement_attachment_urls
            if legal and legal.announcement_attachment_urls
            else [],
        }
        audit_payload = {
            "detail_archive_path": audit.detail_archive_path if audit else None,
            "source_json_path": audit.source_json_path if audit else None,
            "json_file": audit.source_json_path if audit else None,
            "__file_path": audit.source_json_path if audit else None,
            "list_payload_path": audit.list_payload_path if audit else None,
            "detail_text_path": audit.detail_text_path if audit else None,
            "component_payload_path": audit.component_payload_path if audit else None,
            "notice_text_path": audit.notice_text_path if audit else None,
            "desc_text_path": audit.desc_text_path if audit else None,
            "attachment_manifest_path": audit.attachment_manifest_path
            if audit
            else None,
            "image_manifest_path": audit.image_manifest_path if audit else None,
            "extraction_confidence": float(audit.extraction_confidence)
            if audit and audit.extraction_confidence is not None
            else None,
            "evidence_span": audit.evidence_span if audit else None,
            "evidence_source": audit.evidence_source if audit else None,
            "extraction_version": audit.extraction_version if audit else None,
            "community_name_source": audit.community_name_source if audit else None,
            "community_name_confidence": float(audit.community_name_confidence)
            if audit and audit.community_name_confidence is not None
            else None,
            "community_stable_key": audit.community_stable_key if audit else None,
            "community_raw_name": audit.community_raw_name if audit else None,
            "beike_community_id": audit.beike_community_id if audit else None,
            "is_processed": audit.is_processed if audit else None,
            "detail_captured": audit.detail_captured if audit else None,
            "detail_fetch_status": audit.detail_fetch_status if audit else None,
            "detail_fetch_attempted_at": self._fmt_dt(audit.detail_fetch_attempted_at)
            if audit
            else None,
            "detail_fetch_attempt_count": audit.detail_fetch_attempt_count
            if audit
            else None,
            "detail_fetch_last_url": audit.detail_fetch_last_url if audit else None,
            "seed_status": audit.seed_status if audit else None,
            "seed_first_seen_at": self._fmt_dt(audit.seed_first_seen_at)
            if audit
            else None,
            "seed_last_seen_at": self._fmt_dt(audit.seed_last_seen_at)
            if audit
            else None,
            "seed_source_page_url": audit.seed_source_page_url if audit else None,
            "detail_status": audit.detail_status if audit else None,
            "detail_last_error": audit.detail_last_error if audit else None,
            "detail_retry_count": audit.detail_retry_count if audit else None,
            "detail_lease_until": self._fmt_dt(audit.detail_lease_until)
            if audit
            else None,
            "analysis_status": audit.analysis_status if audit else None,
            "analysis_ready": audit.analysis_ready if audit else None,
            "analysis_missing_fields": audit.analysis_missing_fields if audit else None,
            "analysis_last_scored_at": self._fmt_dt(audit.analysis_last_scored_at)
            if audit
            else None,
            "analysis_model_version": audit.analysis_model_version if audit else None,
        }

        payload.update(
            {
                key: value
                for key, value in {
                    **risk_payload,
                    **legal_payload,
                    **audit_payload,
                }.items()
                if value not in (None, "", [])
            }
        )
        payload["avm_risk_features"] = {
            **risk_payload,
            "housing_type": listing.housing_type,
            "community_name": listing.community_name,
            "build_year": listing.build_year,
            "total_floors": listing.total_floors,
            "floor_level": listing.floor_level,
            "has_elevator": listing.has_elevator,
            "orientation": listing.orientation,
            "has_keys": listing.has_keys,
            "special_school_tag": listing.special_school_tag,
            "evaluation_price": float(listing.evaluation_price)
            if listing.evaluation_price is not None
            else None,
            "layout": listing.layout,
            "includes_parking": listing.includes_parking,
            "extraction_confidence": audit_payload["extraction_confidence"],
            "evidence_span": audit_payload["evidence_span"],
            "evidence_source": audit_payload["evidence_source"],
            "extraction_version": audit_payload["extraction_version"],
            "community_name_source": audit_payload["community_name_source"],
            "community_name_confidence": audit_payload["community_name_confidence"],
            "community_stable_key": audit_payload["community_stable_key"],
            "community_raw_name": audit_payload["community_raw_name"],
            "beike_community_id": audit_payload["beike_community_id"],
        }
        return merge_canonical_payload_into_flat(payload, listing.canonical_payload)

    def _feature_source_payload_from_rows(
        self,
        listing: PropertyListing,
        risk: PropertyRiskFlags | None,
        audit: PropertyAudit | None,
    ) -> Dict[str, Any]:
        return {
            "item_id": listing.item_id,
            "auction_date": self._fmt_dt(listing.auction_date),
            "province": listing.province,
            "city": listing.city,
            "district": listing.district,
            "community_name": listing.community_name,
            "business_area": listing.business_area,
            "area_sqm": float(listing.area_sqm)
            if listing.area_sqm is not None
            else None,
            "starting_price": float(listing.starting_price)
            if listing.starting_price is not None
            else None,
            "transaction_price": float(listing.transaction_price)
            if listing.transaction_price is not None
            else None,
            "actual_paid_price": float(listing.actual_paid_price)
            if listing.actual_paid_price is not None
            else None,
            "latitude": listing.latitude,
            "longitude": listing.longitude,
            "status": listing.status,
            "auction_round": listing.auction_round,
            "housing_type": listing.housing_type,
            "bid_count": listing.bid_count,
            "apply_count": listing.apply_count,
            "build_year": listing.build_year,
            "total_floors": listing.total_floors,
            "floor_level": listing.floor_level,
            "has_elevator": listing.has_elevator,
            "orientation": listing.orientation,
            "land_right_type": risk.land_right_type if risk else None,
            "is_occupied": risk.is_occupied if risk else None,
            "has_long_lease": risk.has_long_lease if risk else None,
            "clear_delivery": risk.clear_delivery if risk else None,
            "tax_burden": risk.tax_burden if risk else None,
            "is_haunted": risk.is_haunted if risk else None,
            "has_keys": listing.has_keys,
            "property_fee_owed": risk.property_fee_owed if risk else None,
            "special_school_tag": listing.special_school_tag,
            "evaluation_price": float(listing.evaluation_price)
            if listing.evaluation_price is not None
            else None,
            "layout": listing.layout,
            "is_restricted_purchase": risk.is_restricted_purchase if risk else None,
            "includes_parking": listing.includes_parking,
            "is_fractional_share": risk.is_fractional_share if risk else None,
            "tax_is_company_owned": risk.tax_is_company_owned if risk else None,
            "has_lease_before_mortgage": risk.has_lease_before_mortgage
            if risk
            else None,
            "extraction_confidence": float(audit.extraction_confidence)
            if audit and audit.extraction_confidence is not None
            else None,
            "evidence_source": audit.evidence_source if audit else None,
            "extraction_version": audit.extraction_version if audit else None,
            "analysis_ready": audit.analysis_ready if audit else None,
            "analysis_status": audit.analysis_status if audit else None,
        }
