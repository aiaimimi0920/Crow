from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional

DETAIL_BLOCKED_STATES = {"login_redirect", "anti_bot_gate", "empty_html"}
DETAIL_FAILED_STATES = {
    "failed",
    "fetch_failed",
    "timeout",
    "http_error",
    "parse_error",
}


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def derive_collection_state(
    record: Dict[str, Any],
    raw_item: Optional[Dict[str, Any]] = None,
    *,
    event_type: Optional[str] = None,
    existing: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    raw_item = raw_item or {}
    existing = existing or {}
    now = now or datetime.now(timezone.utc)

    source = record.get("source", {}) or {}
    archive = record.get("archive", {}) or {}
    legal_context = record.get("legal_context", {}) or {}
    risk_flags = record.get("risk_flags", {}) or {}
    audit = record.get("audit", {}) or {}

    has_source_url = _present(
        source.get("source_url") or record.get("source_url") or record.get("url")
    )
    has_seed_payload = (
        has_source_url
        or _present(raw_item.get("url"))
        or _present(raw_item.get("source_url"))
    )
    seed_status = "stored" if has_seed_payload else existing.get("seed_status")
    seed_first_seen_at = existing.get("seed_first_seen_at")
    seed_last_seen_at = existing.get("seed_last_seen_at")
    if seed_status == "stored":
        seed_last_seen_at = now
        if not seed_first_seen_at:
            seed_first_seen_at = now
    seed_source_page_url = (
        raw_item.get("source_page_url")
        or raw_item.get("list_page_url")
        or source.get("list_payload_path")
        or record.get("list_payload_path")
        or existing.get("seed_source_page_url")
    )

    detail_fetch_status = str(
        raw_item.get("detail_fetch_status") or existing.get("detail_fetch_status") or ""
    ).strip()
    replay_requested = _present(raw_item.get("detail_replay_requested_at")) or _present(
        raw_item.get("detail_replay_reason")
    )
    has_detail_archive = any(
        _present(source.get("detail_archive_path"))
        or _present(record.get("detail_archive_path"))
        or _present(archive.get(key))
        or _present(record.get(key))
        for key in (
            "detail_text_path",
            "component_payload_path",
            "notice_text_path",
            "desc_text_path",
            "attachment_manifest_path",
            "image_manifest_path",
        )
    )
    detail_captured = bool(
        audit.get("detail_captured")
        or record.get("detail_captured")
        or raw_item.get("detail_captured")
    )
    detail_sidecar_ready = any(
        _present(archive.get(key)) or _present(record.get(key))
        for key in (
            "detail_text_path",
            "component_payload_path",
            "notice_text_path",
            "desc_text_path",
            "attachment_manifest_path",
            "image_manifest_path",
        )
    )
    risk_present = any(_present(value) for value in risk_flags.values())
    legal_present = any(_present(value) for value in legal_context.values())

    detail_status = existing.get("detail_status")
    if replay_requested:
        detail_status = "replay_requested"
    elif detail_fetch_status in DETAIL_BLOCKED_STATES:
        detail_status = "blocked"
    elif detail_fetch_status in DETAIL_FAILED_STATES:
        detail_status = "failed"
    elif detail_captured and (detail_sidecar_ready or risk_present or legal_present):
        detail_status = "enriched"
    elif detail_captured or has_detail_archive:
        detail_status = "archived"
    elif has_source_url:
        detail_status = "pending"

    detail_last_error = existing.get("detail_last_error")
    if detail_fetch_status in DETAIL_BLOCKED_STATES | DETAIL_FAILED_STATES:
        detail_last_error = detail_fetch_status
    elif detail_status in {"archived", "enriched"}:
        detail_last_error = None

    detail_retry_count = _coerce_int(
        raw_item.get(
            "detail_retry_count",
            raw_item.get(
                "detail_fetch_attempt_count", existing.get("detail_retry_count", 0)
            ),
        ),
        0,
    )
    if (
        detail_fetch_status in DETAIL_BLOCKED_STATES | DETAIL_FAILED_STATES
        and detail_retry_count <= 0
    ):
        detail_retry_count = 1

    detail_lease_until = existing.get("detail_lease_until")

    return {
        "seed_status": seed_status,
        "seed_first_seen_at": seed_first_seen_at,
        "seed_last_seen_at": seed_last_seen_at,
        "seed_source_page_url": seed_source_page_url,
        "detail_status": detail_status,
        "detail_last_error": detail_last_error,
        "detail_retry_count": detail_retry_count,
        "detail_lease_until": detail_lease_until,
    }


def derive_stage_state(
    record: Dict[str, Any],
    raw_item: Optional[Dict[str, Any]] = None,
    *,
    event_type: Optional[str] = None,
    existing: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    analysis_requirements: Callable[[Mapping[str, Any], str | None], list[str]]
    | None = None,
    analysis_model_version: str | None = None,
) -> Dict[str, Any]:
    """Legacy projection for existing analysis consumers, outside native writes."""
    from src.avm.stage_projection import derive_analysis_state

    stage = derive_collection_state(
        record, raw_item, event_type=event_type, existing=existing, now=now
    )
    return {
        **stage,
        **derive_analysis_state(
            record,
            stage["detail_status"],
            event_type=event_type,
            existing=existing,
            analysis_requirements=analysis_requirements,
            analysis_model_version=analysis_model_version,
        ),
    }
