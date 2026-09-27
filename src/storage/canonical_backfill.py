from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select

from .canonical_record import CANONICAL_RECORD_SCHEMA_VERSION, build_canonical_payload
from .models import (
    PropertyAudit,
    PropertyLegalContext,
    PropertyListing,
    PropertyRiskFlags,
)


@dataclass(frozen=True)
class CanonicalBackfillResult:
    scanned: int
    changed: int
    applied: bool


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def backfill_canonical_payloads(
    repository, *, apply: bool = False
) -> CanonicalBackfillResult:
    """Populate missing/outdated envelopes; dry-run unless apply is explicit."""

    repository.initialize()
    scanned = 0
    changed = 0
    with repository.session_factory() as session:
        listings = session.scalars(
            select(PropertyListing).order_by(PropertyListing.item_id)
        ).all()
        for listing in listings:
            scanned += 1
            risk = session.get(PropertyRiskFlags, listing.item_id)
            legal = session.get(PropertyLegalContext, listing.item_id)
            audit = session.get(PropertyAudit, listing.item_id)
            legacy = repository._listing_payload_from_rows(listing, risk, legal, audit)
            canonical = build_canonical_payload(
                legacy,
                repository._build_collection_record(legacy),
                previous=listing.canonical_payload,
                captured_at=listing.updated_at or listing.created_at,
            )
            if (
                listing.record_schema_version == CANONICAL_RECORD_SCHEMA_VERSION
                and _stable_json(listing.canonical_payload) == _stable_json(canonical)
            ):
                continue
            changed += 1
            if apply:
                listing.record_schema_version = CANONICAL_RECORD_SCHEMA_VERSION
                listing.canonical_payload = canonical
        if apply:
            session.commit()
        else:
            session.rollback()
    return CanonicalBackfillResult(scanned=scanned, changed=changed, applied=apply)


__all__ = ["CanonicalBackfillResult", "backfill_canonical_payloads"]
