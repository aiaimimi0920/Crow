from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from src.storage.utc_datetime import UtcNaiveDateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UtcNaiveDateTime(), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UtcNaiveDateTime(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PropertyListing(Base, TimestampMixin):
    __tablename__ = "property_listing"

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_item_id: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_title: Mapped[str | None] = mapped_column(Text)
    source_platform: Mapped[str | None] = mapped_column(String(32))
    record_schema_version: Mapped[int | None] = mapped_column(Integer)
    canonical_payload: Mapped[dict | None] = mapped_column(JSON)

    status: Mapped[str | None] = mapped_column(String(32))
    auction_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    auction_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    auction_round: Mapped[int | None] = mapped_column(Integer)
    transaction_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    starting_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    actual_paid_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    evaluation_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    deposit: Mapped[float | None] = mapped_column(Numeric(18, 2))
    apply_count: Mapped[int | None] = mapped_column(Integer)
    bid_count: Mapped[int | None] = mapped_column(Integer)
    bidder_count: Mapped[int | None] = mapped_column(Integer)
    watch_count: Mapped[int | None] = mapped_column(Integer)
    reminder_count: Mapped[int | None] = mapped_column(Integer)
    view_count: Mapped[int | None] = mapped_column(Integer)

    full_address: Mapped[str | None] = mapped_column(Text)
    province: Mapped[str | None] = mapped_column(String(64))
    city: Mapped[str | None] = mapped_column(String(64), index=True)
    district: Mapped[str | None] = mapped_column(String(64), index=True)
    business_area: Mapped[str | None] = mapped_column(String(128), index=True)
    community_name: Mapped[str | None] = mapped_column(String(256), index=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    coordinate_source: Mapped[str | None] = mapped_column(String(64))

    housing_type: Mapped[str | None] = mapped_column(String(32), index=True)
    area_sqm: Mapped[float | None] = mapped_column(Numeric(12, 2))
    gross_area_sqm: Mapped[float | None] = mapped_column(Numeric(12, 2))
    interior_area_sqm: Mapped[float | None] = mapped_column(Numeric(12, 2))
    land_area_sqm: Mapped[float | None] = mapped_column(Numeric(12, 2))
    ownership_share_ratio: Mapped[float | None] = mapped_column(Numeric(10, 6))
    layout: Mapped[str | None] = mapped_column(String(128))
    build_year: Mapped[int | None] = mapped_column(Integer)
    total_floors: Mapped[int | None] = mapped_column(Integer)
    floor_level: Mapped[str | None] = mapped_column(String(32))
    has_elevator: Mapped[bool | None] = mapped_column(Boolean)
    orientation: Mapped[str | None] = mapped_column(String(32))
    includes_parking: Mapped[bool | None] = mapped_column(Boolean)
    special_school_tag: Mapped[bool | None] = mapped_column(Boolean)
    has_keys: Mapped[bool | None] = mapped_column(Boolean)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_reason: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), server_default=func.now())


class PropertyRiskFlags(Base, TimestampMixin):
    __tablename__ = "property_risk_flags"

    item_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("property_listing.item_id", ondelete="CASCADE"), primary_key=True
    )
    land_right_type: Mapped[str | None] = mapped_column(String(32))
    is_occupied: Mapped[bool | None] = mapped_column(Boolean)
    has_long_lease: Mapped[bool | None] = mapped_column(Boolean)
    clear_delivery: Mapped[bool | None] = mapped_column(Boolean)
    tax_burden: Mapped[str | None] = mapped_column(String(64))
    property_fee_owed: Mapped[bool | None] = mapped_column(Boolean)
    is_restricted_purchase: Mapped[bool | None] = mapped_column(Boolean)
    is_fractional_share: Mapped[bool | None] = mapped_column(Boolean)
    tax_is_company_owned: Mapped[bool | None] = mapped_column(Boolean)
    is_haunted: Mapped[bool | None] = mapped_column(Boolean)
    has_lease_before_mortgage: Mapped[bool | None] = mapped_column(Boolean)


class PropertyLegalContext(Base, TimestampMixin):
    __tablename__ = "property_legal_context"

    item_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("property_listing.item_id", ondelete="CASCADE"), primary_key=True
    )
    court_name: Mapped[str | None] = mapped_column(String(256))
    case_number: Mapped[str | None] = mapped_column(String(256))
    appraisal_agency_name: Mapped[str | None] = mapped_column(String(256))
    appraisal_benchmark_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    appraisal_report_urls: Mapped[list | None] = mapped_column(JSON)
    announcement_attachment_urls: Mapped[list | None] = mapped_column(JSON)


class PropertyAudit(Base, TimestampMixin):
    __tablename__ = "property_audit"

    item_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("property_listing.item_id", ondelete="CASCADE"), primary_key=True
    )
    detail_archive_path: Mapped[str | None] = mapped_column(Text)
    source_json_path: Mapped[str | None] = mapped_column(Text)
    list_payload_path: Mapped[str | None] = mapped_column(Text)
    detail_text_path: Mapped[str | None] = mapped_column(Text)
    component_payload_path: Mapped[str | None] = mapped_column(Text)
    notice_text_path: Mapped[str | None] = mapped_column(Text)
    desc_text_path: Mapped[str | None] = mapped_column(Text)
    attachment_manifest_path: Mapped[str | None] = mapped_column(Text)
    image_manifest_path: Mapped[str | None] = mapped_column(Text)
    extraction_confidence: Mapped[float | None] = mapped_column(Numeric(6, 4))
    evidence_span: Mapped[str | None] = mapped_column(Text)
    evidence_source: Mapped[str | None] = mapped_column(String(64))
    extraction_version: Mapped[str | None] = mapped_column(String(64))
    community_name_source: Mapped[str | None] = mapped_column(String(64))
    community_name_confidence: Mapped[float | None] = mapped_column(Numeric(6, 4))
    community_stable_key: Mapped[str | None] = mapped_column(String(512), index=True)
    community_raw_name: Mapped[str | None] = mapped_column(String(256))
    beike_community_id: Mapped[str | None] = mapped_column(String(128), index=True)
    is_processed: Mapped[bool | None] = mapped_column(Boolean)
    detail_captured: Mapped[bool | None] = mapped_column(Boolean)
    detail_fetch_status: Mapped[str | None] = mapped_column(String(64))
    detail_fetch_attempted_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime())
    detail_fetch_attempt_count: Mapped[int | None] = mapped_column(Integer)
    detail_fetch_last_url: Mapped[str | None] = mapped_column(Text)
    seed_status: Mapped[str | None] = mapped_column(String(32), index=True)
    seed_first_seen_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime())
    seed_last_seen_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime())
    seed_source_page_url: Mapped[str | None] = mapped_column(Text)
    detail_status: Mapped[str | None] = mapped_column(String(32), index=True)
    detail_last_error: Mapped[str | None] = mapped_column(Text)
    detail_retry_count: Mapped[int | None] = mapped_column(Integer)
    detail_lease_until: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime())
    analysis_status: Mapped[str | None] = mapped_column(String(32), index=True)
    analysis_ready: Mapped[bool | None] = mapped_column(Boolean, index=True)
    analysis_missing_fields: Mapped[list | None] = mapped_column(JSON)
    analysis_last_scored_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime())
    analysis_model_version: Mapped[str | None] = mapped_column(String(64))


class PropertySearchTask(Base, TimestampMixin):
    __tablename__ = "property_search_task"

    task_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    location_code: Mapped[str] = mapped_column(String(16), index=True)
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    sort_param: Mapped[str | None] = mapped_column(String(16), index=True)
    next_page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_page: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    leased_by: Mapped[str | None] = mapped_column(String(128), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)
    zero_bid_terminated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime())


class CollectionSeedScanJob(Base, TimestampMixin):
    __tablename__ = "fapai_seed_scan_job"

    job_key: Mapped[str] = mapped_column(String(192), primary_key=True)
    province: Mapped[str | None] = mapped_column(String(64), index=True)
    city: Mapped[str | None] = mapped_column(String(64), index=True)
    district: Mapped[str | None] = mapped_column(String(64), index=True)
    location_code: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    source_url_template: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    completed_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)


class CollectionSeedScanProgress(Base, TimestampMixin):
    __tablename__ = "fapai_seed_scan_progress"

    progress_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    job_key: Mapped[str] = mapped_column(
        String(192),
        ForeignKey("fapai_seed_scan_job.job_key", ondelete="CASCADE"),
        index=True,
    )
    sort_key: Mapped[str] = mapped_column(String(64), index=True)
    sort_name: Mapped[str | None] = mapped_column(String(128))
    st_param: Mapped[str] = mapped_column(String(16), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_page: Mapped[int | None] = mapped_column(Integer)
    last_success_page: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    leased_by: Mapped[str | None] = mapped_column(String(128), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)
    last_fetch_url: Mapped[str | None] = mapped_column(Text)
    last_item_count: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)
    last_rescan_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)
    rescan_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (UniqueConstraint("job_key", "sort_key", name="uq_fapai_seed_scan_progress_job_sort"),)


class CollectionSeedItem(Base, TimestampMixin):
    __tablename__ = "fapai_seed_item"
    __table_args__ = (Index("ix_fapai_seed_item_status_first_seen", "status", "first_seen_at"),)

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_item_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source_platform: Mapped[str | None] = mapped_column(String(32), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_detail", index=True)
    first_seen_job_key: Mapped[str | None] = mapped_column(String(192), index=True)
    first_seen_sort_key: Mapped[str | None] = mapped_column(String(64), index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)
    source_payload: Mapped[dict | None] = mapped_column(JSON)
    detail_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detail_last_error: Mapped[str | None] = mapped_column(Text)
    detail_leased_by: Mapped[str | None] = mapped_column(String(128), index=True)
    detail_lease_until: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)
    detail_completed_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)
    final_json_path: Mapped[str | None] = mapped_column(Text)
    selected_json_path: Mapped[str | None] = mapped_column(Text)


class CollectionAnalysisRun(Base, TimestampMixin):
    __tablename__ = "fapai_analysis_run"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("fapai_seed_item.item_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    candidate_models: Mapped[list | None] = mapped_column(JSON)
    arbiter_model: Mapped[str | None] = mapped_column(String(128))
    arbiter_independent_model: Mapped[bool | None] = mapped_column(Boolean)
    artifact_paths: Mapped[dict | None] = mapped_column(JSON)
    receipt: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)

    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "pipeline_version",
            "input_sha256",
            name="uq_fapai_analysis_run_item_version_input",
        ),
    )


class CollectionSeedOccurrence(Base):
    __tablename__ = "fapai_seed_occurrence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurrence_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    item_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("fapai_seed_item.item_id", ondelete="CASCADE"),
        index=True,
    )
    job_key: Mapped[str] = mapped_column(String(192), index=True)
    progress_key: Mapped[str] = mapped_column(String(256), index=True)
    sort_key: Mapped[str] = mapped_column(String(64), index=True)
    sort_name: Mapped[str | None] = mapped_column(String(128))
    st_param: Mapped[str] = mapped_column(String(16), index=True)
    page: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rank: Mapped[int | None] = mapped_column(Integer)
    source_page_url: Mapped[str | None] = mapped_column(Text)
    source_final_url: Mapped[str | None] = mapped_column(Text)
    raw_item: Mapped[dict | None] = mapped_column(JSON)
    seen_at: Mapped[datetime] = mapped_column(UtcNaiveDateTime(), server_default=func.now(), nullable=False, index=True)


class PropertyIngestEvent(Base):
    __tablename__ = "property_ingest_event"
    __table_args__ = (Index("ix_property_ingest_event_type_created", "event_type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    event_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcNaiveDateTime(), server_default=func.now(), nullable=False)


class ManualReviewReceipt(Base, TimestampMixin):
    __tablename__ = "manual_review_receipt"

    action: Mapped[str] = mapped_column(String(128), primary_key=True)
    ready_signal: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(128))
    receipt_updated_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)


class ManualReviewReceiptJob(Base, TimestampMixin):
    __tablename__ = "manual_review_receipt_job"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    receipt_action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    receipt_ready_signal: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    maintenance_options: Mapped[dict | None] = mapped_column(JSON)
    result_summary: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcNaiveDateTime(), index=True)


class ManualReviewReceiptOperation(Base):
    __tablename__ = "manual_review_receipt_operation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ready_signal: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str | None] = mapped_column(String(64))
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str | None] = mapped_column(String(128))
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    maintenance_job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    deleted: Mapped[bool | None] = mapped_column(Boolean)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(UtcNaiveDateTime(), nullable=False, index=True, server_default=func.now())


# Public import compatibility only. Tables, indexes, FKs and stored rows keep their
# historical names; canonical Python classes describe the source-neutral engine.
FapaiSeedScanJob = CollectionSeedScanJob
FapaiSeedScanProgress = CollectionSeedScanProgress
FapaiSeedItem = CollectionSeedItem
FapaiAnalysisRun = CollectionAnalysisRun
FapaiSeedOccurrence = CollectionSeedOccurrence
