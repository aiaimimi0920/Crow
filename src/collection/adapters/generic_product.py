from __future__ import annotations

import datetime
import json
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..contracts import NumberParser, Record
from ..search_task_policy import GenericSearchTaskPolicy, SearchTaskPolicy
from ..seed_list_parser import (
    GenericJsonSeedListParser,
    SeedListParser,
    normalize_source_item_id,
)
from ..seed_scan_policy import GenericSeedScanPolicy, SeedScanPolicy


def _first_non_empty(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", []):
            return value
    return None


@dataclass(frozen=True)
class GenericProductAdapter:
    """Default domain policy for collecting arbitrary product-like records."""

    source_platform: str = "generic"
    collects_avm_risk: bool = False
    bootstraps_legacy_search_tasks: bool = False

    def __post_init__(self) -> None:
        policy = GenericSeedScanPolicy(source_platform=self.source_platform)
        object.__setattr__(self, "source_platform", policy.source_platform)

    @property
    def search_task_policy(self) -> SearchTaskPolicy:
        return GenericSearchTaskPolicy(source_platform=self.source_platform)

    @property
    def seed_scan_policy(self) -> SeedScanPolicy:
        return GenericSeedScanPolicy(source_platform=self.source_platform)

    @property
    def analysis_profile(self) -> GenericProductAnalysisProfile:
        return GenericProductAnalysisProfile()

    def create_seed_list_parser(self, legacy_probe: Any) -> SeedListParser:
        del legacy_probe
        return GenericJsonSeedListParser()

    def item_id(self, item: Mapping[str, Any]) -> str:
        raw_source_item_id = _first_non_empty(
            item, "source_item_id", "id", "item_id", "sku"
        )
        if raw_source_item_id is None:
            raise ValueError("collection item is missing source_item_id/id/item_id/sku")
        source_item_id = normalize_source_item_id(str(raw_source_item_id))
        return self.seed_scan_policy.storage_item_id(source_item_id)

    def build_seed_record(
        self,
        item: Mapping[str, Any],
        *,
        parse_number: NumberParser,
        safe_int: NumberParser,
    ) -> Record:
        del parse_number, safe_int
        record = {
            str(key): value for key, value in item.items() if value not in (None, "")
        }
        raw_source_item_id = _first_non_empty(
            item, "source_item_id", "id", "item_id", "sku"
        )
        if raw_source_item_id is None:
            raise ValueError("collection item is missing source_item_id/id/item_id/sku")
        source_item_id = normalize_source_item_id(str(raw_source_item_id))
        item_id = self.item_id(item)
        declared_platform = str(item.get("source_platform") or "").strip()
        if declared_platform and declared_platform != self.source_platform:
            raise ValueError(
                "collection item source_platform does not match its adapter"
            )
        title = _first_non_empty(item, "source_title", "title", "name")
        source_url = _first_non_empty(item, "source_url", "url", "detail_url")
        record.update(
            {
                "id": item_id,
                "item_id": item_id,
                "source_item_id": source_item_id,
                "source_platform": self.source_platform,
                "is_processed": False,
            }
        )
        if str(raw_source_item_id) != source_item_id:
            record.setdefault("raw_source_item_id", str(raw_source_item_id))
        if title is not None:
            record.setdefault("title", title)
            record.setdefault("source_title", title)
        if source_url is not None:
            record.setdefault("url", source_url)
            record.setdefault("source_url", source_url)
        return record

    def accepts_seed(self, item: Mapping[str, Any], record: Mapping[str, Any]) -> bool:
        del record
        return not bool(item.get("skip_collection", False))

    def sync_record(self, record: MutableMapping[str, Any]) -> None:
        del record

    def build_storage_record(self, record: Record) -> Record:
        from ..record_schema import build_collection_record

        return build_collection_record(
            record, default_source_platform=self.source_platform
        )

    def partition_key(self, record: Mapping[str, Any]) -> str:
        raw = _first_non_empty(record, "collected_at", "published_at", "updated_at")
        if raw:
            return str(raw).split(" ", 1)[0][:10] or "unknown"
        return datetime.datetime.now(datetime.timezone.utc).date().isoformat()

    def preserve_seed_values(
        self,
        record: MutableMapping[str, Any],
        existing: Mapping[str, Any],
    ) -> None:
        for key, value in existing.items():
            if value not in (None, "", []) and record.get(key) in (None, "", []):
                record[key] = value

    def prepare_detail_record(
        self,
        record: MutableMapping[str, Any],
        *,
        existing: Mapping[str, Any],
        item_id: str,
    ) -> None:
        for key, value in existing.items():
            if value not in (None, "", []) and record.get(key) in (None, "", []):
                record[key] = value
        source_item_id = _first_non_empty(
            existing,
            "source_item_id",
            "raw_source_item_id",
        ) or _first_non_empty(
            record,
            "source_item_id",
            "raw_source_item_id",
        )
        if source_item_id is None:
            raise ValueError("generic detail record is missing its source_item_id")
        record["id"] = item_id
        record["item_id"] = item_id
        record["source_item_id"] = str(source_item_id)
        record["source_platform"] = (
            existing.get("source_platform") or self.source_platform
        )
        source_url = self.source_url(existing) or self.source_url(record)
        if source_url:
            record["url"] = source_url
            record["source_url"] = source_url

    def accepts_detail(self, record: Mapping[str, Any]) -> bool:
        return str(record.get("status") or "").strip().lower() not in {
            "cancelled",
            "canceled",
            "deleted",
            "removed",
        }

    def retry_reason(self, record: Mapping[str, Any]) -> str | None:
        del record
        return None

    def finalize_detail_record(self, record: MutableMapping[str, Any]) -> None:
        record["detail_captured"] = True
        record["is_processed"] = True

    def archive_date(self, record: Mapping[str, Any]) -> Any:
        return _first_non_empty(
            record, "collected_at", "published_at", "updated_at"
        ) or datetime.datetime.now(datetime.timezone.utc)

    def source_url(self, record: Mapping[str, Any]) -> str | None:
        value = _first_non_empty(record, "source_url", "url", "detail_url")
        return str(value) if value is not None else None

    def quality_summary(self, record: Mapping[str, Any]) -> str:
        populated = sum(value not in (None, "", []) for value in record.values())
        return f"fields={populated}"

    def detail_replay_reason(self, record: Mapping[str, Any]) -> str | None:
        if not record.get("detail_archive_path") and self.accepts_detail(record):
            return "missing_detail_capture"
        return None

    def detail_replay_url(self, record: Mapping[str, Any]) -> str | None:
        return self.source_url(record)

    def blocked_capture_reason(self, content: str) -> str | None:
        return "empty_html" if len(content.strip()) < 200 else None

    def location_prompt(self, *, address: str, title: str) -> str | None:
        del address, title
        return None


@dataclass(frozen=True)
class GenericProductAnalysisProfile:
    """Evidence rules that make no assumptions about a product category."""

    money_fields: frozenset[str] = field(default_factory=frozenset)
    area_fields: frozenset[str] = field(default_factory=frozenset)
    ratio_fields: frozenset[str] = field(default_factory=frozenset)
    count_fields: frozenset[str] = field(default_factory=frozenset)
    boolean_fields: frozenset[str] = field(default_factory=frozenset)
    datetime_fields: frozenset[str] = field(default_factory=frozenset)
    derived_fields: frozenset[str] = field(default_factory=frozenset)
    system_fields: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "id",
                "source_item_id",
                "source_platform",
                "source_url",
                "url",
                "source_title",
                "title",
                "is_processed",
                "detail_captured",
            }
        )
    )
    high_risk_fields: frozenset[str] = field(default_factory=frozenset)
    field_keywords: Mapping[str, Sequence[str]] = field(default_factory=dict)

    def adjudication_prompt(
        self,
        *,
        item_id: str,
        conflicts: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
        source_text: str,
    ) -> str:
        return f"""
# Role
You are Crow's evidence adjudicator. Resolve only conflicts among three independent extraction results.

# Hard rules
1. Return only fields present in conflicts; never rewrite locked fields.
2. Every non-null value must cite a short exact fragment from the source evidence.
3. A value may come from a candidate or be new only when the source explicitly supports it.
4. If evidence is missing, ambiguous, or contradictory, use null and needs_review.
5. Return JSON only, without Markdown.

# Output schema
{{"decisions": {{"field.path": {{"value": null, "decision": "candidate_1|candidate_2|candidate_3|new|needs_review", "evidence": "", "confidence": 0.0}}}}}}

# Item
{item_id}

# Three independent results
{json.dumps(list(candidates), ensure_ascii=False, sort_keys=True)}

# Conflicts
{json.dumps(conflicts, ensure_ascii=False, sort_keys=True)}

# Source evidence
{source_text[:100000]}
""".strip()

    def derive_final_fields(self, field_values: MutableMapping[str, Any]) -> None:
        del field_values
