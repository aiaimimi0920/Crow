from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import and_, case, create_engine, func, not_, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .canonical_record import (
    CANONICAL_RECORD_SCHEMA_VERSION,
    build_canonical_payload,
    merge_canonical_payload_into_flat,
)
from .models import (
    Base,
    FapaiAnalysisRun,
    FapaiSeedItem,
    FapaiSeedOccurrence,
    FapaiSeedScanJob,
    FapaiSeedScanProgress,
    ManualReviewReceipt,
    ManualReviewReceiptJob,
    ManualReviewReceiptOperation,
    PropertyAudit,
    PropertyIngestEvent,
    PropertyLegalContext,
    PropertyListing,
    PropertyRiskFlags,
    PropertySearchTask,
)

RepositoryClock = Callable[[], datetime]
_INJECTED_REPOSITORY_CLOCK: ContextVar[RepositoryClock | None] = ContextVar(
    "fapai_repository_clock",
    default=None,
)


@contextmanager
def use_repository_clock(clock: RepositoryClock) -> Iterator[None]:
    """Inject a deterministic UTC clock for one request or test context.

    Repository callers retain UTC-naive Python values; the column type handles
    physical storage. The callable may return an aware instant or naive UTC.
    """
    if not callable(clock):
        raise TypeError("repository clock must be callable")
    token = _INJECTED_REPOSITORY_CLOCK.set(clock)
    try:
        yield
    finally:
        _INJECTED_REPOSITORY_CLOCK.reset(token)


def _parse_dt(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return _coerce_naive_utc(value)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in {"%Y-%m-%d", "%Y/%m/%d"}:
                dt = dt.replace(hour=0, minute=0, second=0)
            return _coerce_naive_utc(dt)
        except ValueError:
            continue
    return None


def _coerce_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=None)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _utc_now() -> datetime:
    injected_clock = _INJECTED_REPOSITORY_CLOCK.get()
    value = _coerce_naive_utc(
        injected_clock() if injected_clock is not None else datetime.now(timezone.utc)
    )
    if value is None:
        raise RuntimeError("utc clock returned no value")
    return value


def _lease_reclaimable(
    lease_until: Optional[datetime],
    *,
    now: datetime,
) -> bool:
    # The persisted expiry belongs to the holder; a contender cannot shorten it.
    normalized_lease_until = _coerce_naive_utc(lease_until)
    return (
        normalized_lease_until is None
        or normalized_lease_until <= _coerce_naive_utc(now)
    )


def _cooldown_active(
    updated_at: Optional[datetime], *, now: datetime, cutoff: Optional[datetime]
) -> bool:
    if cutoff is None:
        return False
    normalized_updated_at = _coerce_naive_utc(updated_at)
    if normalized_updated_at is None:
        return False
    if normalized_updated_at - now > timedelta(seconds=300):
        return False
    return normalized_updated_at >= cutoff


def _manual_review_payload_fingerprint(payload: Any) -> str:
    normalized = json.dumps(
        payload if payload is not None else {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# Keep the locked candidate window small so detail/analysis claim paths do not
# hold broad row locks while filtering candidates in Python.
SEED_ITEM_CLAIM_BATCH_LIMIT = 16
# Avoid starving long-stuck retryable failures behind a large pending backlog.
SEED_ITEM_STALE_FAILED_PRIORITY_SECONDS = 300


def _seed_claim_cursor_clause(
    priority_expr,
    sort_first_seen_at,
    last_cursor: tuple[int, datetime, str] | None,
):
    if last_cursor is None:
        return None
    last_priority, last_first_seen_at, last_item_id = last_cursor
    return or_(
        priority_expr > last_priority,
        and_(priority_expr == last_priority, sort_first_seen_at > last_first_seen_at),
        and_(
            priority_expr == last_priority,
            sort_first_seen_at == last_first_seen_at,
            FapaiSeedItem.item_id > last_item_id,
        ),
    )


def _normalized_seed_text(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    text_value = str(value).strip()
    return text_value or None


def _shared_data_root_candidates() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for env_name in (
        "FAPAI_SHARED_ARTIFACT_ROOT",
        "FAPAI_SHARED_DATA_ROOT_HOST",
        "CROW_DATA_ROOT_HOST",
        "FAPAI_DATA_ROOT_HOST",
        "FAPAI_SHARED_DATA_ROOT",
        "FAPAI_DATA_ROOT",
    ):
        raw = str(os.getenv(env_name) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(path)
    return candidates


def _shared_artifact_relative_path(path_value: str) -> str | None:
    """Extract a relative path from a Windows/UNC CrowData or legacy FPFData artifact path.

    Workers may run on Windows and persist their host path in the central DB.
    The API runs in Linux, so only the portion below the shared management root is
    portable. Reject traversal rather than resolving arbitrary host paths.
    """
    normalized = path_value.replace("\\", "/")
    lowered = normalized.lower()
    markers = [(lowered.find(marker), marker) for marker in ("/fpfdata/", "/crowdata/") if marker in lowered]
    if not markers:
        return None
    marker_index, marker = min(markers)
    relative = normalized[marker_index + len(marker) :].lstrip("/")
    if not relative:
        return None
    parts = [part for part in relative.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        return None
    return "/".join(parts)


def _resolve_from_shared_artifact_roots(path_value: str) -> str | None:
    relative = _shared_artifact_relative_path(path_value)
    if not relative:
        return None
    for root in _shared_data_root_candidates():
        try:
            candidate = (root / relative).resolve()
            resolved_root = root.resolve()
            candidate.relative_to(resolved_root)
        except (OSError, ValueError):
            continue
        if candidate.is_file():
            return str(candidate)
    return None


def _resolve_collection_artifact_path(path_value: Any) -> str | None:
    text = str(path_value or "").strip()
    if not text:
        return None
    if os.path.isfile(text):
        return text

    shared_candidate = _resolve_from_shared_artifact_roots(text)
    if shared_candidate:
        return shared_candidate

    normalized = text.replace("\\", "/")
    if not normalized.startswith("/data/"):
        return text

    relative_parts = [part for part in normalized[len("/data/") :].split("/") if part]
    if not relative_parts:
        return text

    for root in _shared_data_root_candidates():
        candidate = root.joinpath(*relative_parts)
        if candidate.is_file():
            return str(candidate)
    return text


def _taobao_location_override_path() -> Path:
    configured = str(os.getenv("FAPAI_TAOBAO_LOCATIONS_FILE") or "").strip()
    if configured:
        return Path(configured)
    return (
        Path(__file__).resolve().parents[2]
        / "datas"
        / "taobao_sf_location_overrides.json"
    )


def _load_taobao_region_override_filter() -> tuple[set[str], set[str]]:
    path = _taobao_location_override_path()
    if not path.exists():
        return set(), set()
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), set()
    if not isinstance(decoded, dict):
        return set(), set()
    raw_locations = decoded.get("locations") or []
    raw_replace_admin_provinces = decoded.get("replace_admin_provinces") or []
    override_codes = {
        str(item.get("location_code") or item.get("code") or "").strip()
        for item in raw_locations
        if isinstance(item, dict)
    }
    replace_admin_provinces = {
        str(item or "").strip() for item in raw_replace_admin_provinces
    }
    return {code for code in override_codes if code}, {
        province for province in replace_admin_provinces if province
    }


@dataclass
class DatabaseSettings:
    url: str | None
    echo: bool = False
    enable_postgis: bool = True
    auto_create: bool = False
    enabled: bool = True


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


__all__ = [name for name in globals() if not name.startswith("__")]
