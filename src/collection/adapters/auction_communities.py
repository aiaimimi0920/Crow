"""Offline community-name standardization for collected auction facts.

The resolver is intentionally offline-first: it can consume a locally maintained
Beike/Lianjia-style community index when available, and falls back to a stable
geographic anchor when the community is not in that index.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

AUDIT_KEYS = (
    "community_name_source",
    "community_name_confidence",
    "community_stable_key",
    "community_raw_name",
    "beike_community_id",
)

COMMUNITY_KEYS = ("community_name", "所属小区", "小区", "小区名称")
ADDRESS_KEYS = (
    "full_address",
    "完整地址",
    "地点",
    "location",
    "address",
    "title",
    "标题",
)
CITY_KEYS = ("city", "城市")
DISTRICT_KEYS = ("district", "区", "行政区")
BUSINESS_AREA_KEYS = ("business_area", "最靠近商圈", "business_area_name")

BLANK_VALUES = {"", "UNK", "unknown", "None", "null", "无", "暂无", "未知"}
DEFAULT_INDEX_ENV_VAR = "FAPAI_COMMUNITY_INDEX_PATH"
DEFAULT_INDEX_PATHS = (
    Path("datas/beike_communities.json"),
    Path("datas/community_index.json"),
    Path("datas/communities.json"),
)

_DEFAULT_INDEX_CACHE: CommunityIndex | None = None
_DEFAULT_INDEX_CACHE_PATH: Path | None = None


@dataclass(frozen=True)
class CommunityResolution:
    name: str
    source: str
    confidence: float
    stable_key: str
    raw_name: str = ""
    beike_id: str | None = None


@dataclass(frozen=True)
class CommunityEntry:
    city: str
    district: str
    canonical_name: str
    aliases: tuple[str, ...] = ()
    beike_id: str | None = None


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in BLANK_VALUES else text


def _first_text(payload: dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = _clean_text(payload.get(key))
        if value:
            return value
    return ""


def normalize_community_token(value: Any) -> str:
    """Normalize names enough for matching without changing the canonical label."""
    text = _clean_text(value)
    if not text:
        return ""
    text = re.sub(r"\s+", "", text)
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III")
    text = re.sub(r"[\-—_·・,，。:：;；/\\]+", "", text)
    for suffix in ("小区", "住宅小区", "公寓小区"):
        if len(text) > len(suffix) + 1 and text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text.lower()


def _location_key(city: Any, district: Any) -> tuple[str, str]:
    return (_clean_text(city), _clean_text(district))


class CommunityIndex:
    """Small in-memory canonical community index."""

    def __init__(self, entries: Iterable[CommunityEntry] = ()):
        self.entries = list(entries)
        self._by_location_and_token: dict[
            tuple[str, str, str], tuple[CommunityEntry, str]
        ] = {}
        self._by_location: dict[tuple[str, str], list[CommunityEntry]] = {}
        for entry in self.entries:
            location = _location_key(entry.city, entry.district)
            self._by_location.setdefault(location, []).append(entry)
            tokens = [(entry.canonical_name, "exact")]
            tokens.extend((alias, "alias") for alias in entry.aliases)
            for name, kind in tokens:
                token = normalize_community_token(name)
                if token:
                    self._by_location_and_token[(entry.city, entry.district, token)] = (
                        entry,
                        kind,
                    )

    @classmethod
    def empty(cls) -> "CommunityIndex":
        return cls(())

    @classmethod
    def from_rows(cls, rows: Iterable[dict[str, Any]]) -> "CommunityIndex":
        entries: list[CommunityEntry] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            city = _first_text(row, ("city", "城市"))
            district = _first_text(row, ("district", "区", "行政区"))
            canonical_name = _first_text(
                row,
                ("canonical_name", "name", "community_name", "小区名称", "所属小区"),
            )
            if not canonical_name:
                continue
            aliases_raw = row.get("aliases") or row.get("别名") or []
            if isinstance(aliases_raw, str):
                aliases = tuple(
                    part.strip()
                    for part in re.split(r"[,，;；|/、]+", aliases_raw)
                    if part.strip()
                )
            elif isinstance(aliases_raw, list):
                aliases = tuple(
                    str(part).strip() for part in aliases_raw if str(part).strip()
                )
            else:
                aliases = ()
            entries.append(
                CommunityEntry(
                    city=city,
                    district=district,
                    canonical_name=canonical_name,
                    aliases=aliases,
                    beike_id=_first_text(row, ("beike_id", "ke_id", "id")) or None,
                )
            )
        return cls(entries)

    @classmethod
    def from_path(cls, path: str | Path | None) -> "CommunityIndex":
        if not path:
            return cls.empty()
        index_path = Path(path)
        if not index_path.exists():
            return cls.empty()
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return cls.from_rows(payload)
        if isinstance(payload, dict):
            rows = (
                payload.get("communities")
                or payload.get("items")
                or payload.get("rows")
            )
            if isinstance(rows, list):
                return cls.from_rows(rows)
        return cls.empty()

    def match_name(
        self, *, city: str, district: str, raw_name: str
    ) -> tuple[CommunityEntry, str] | None:
        token = normalize_community_token(raw_name)
        if not token:
            return None
        locations = [_location_key(city, district)]
        if city or district:
            locations.append(("", ""))
        for location in locations:
            match = self._by_location_and_token.get((location[0], location[1], token))
            if match:
                return match
        return None

    def match_address(
        self, *, city: str, district: str, address: str
    ) -> CommunityEntry | None:
        text_token = normalize_community_token(address)
        if not text_token:
            return None
        candidates = self._by_location.get(_location_key(city, district), [])
        candidates += self._by_location.get(("", ""), [])
        best: CommunityEntry | None = None
        best_len = 0
        for entry in candidates:
            names = (entry.canonical_name, *entry.aliases)
            for name in names:
                token = normalize_community_token(name)
                if token and token in text_token and len(token) > best_len:
                    best = entry
                    best_len = len(token)
        return best


def _default_index_path() -> Path | None:
    env_path = _clean_text(os.getenv(DEFAULT_INDEX_ENV_VAR))
    paths: list[Path] = []
    if env_path:
        paths.append(Path(env_path))
    paths.extend(DEFAULT_INDEX_PATHS)

    for path in paths:
        if path.exists():
            return path.resolve()
    return None


def load_default_community_index(*, refresh: bool = False) -> CommunityIndex:
    """Load the local community index used by live collection.

    The project does not vendor a nationwide Beike dataset. Operators can provide
    one via FAPAI_COMMUNITY_INDEX_PATH or the conventional datas/*.json paths.
    Missing files degrade to an empty index so collection can keep running.
    """
    global _DEFAULT_INDEX_CACHE, _DEFAULT_INDEX_CACHE_PATH
    selected_path = _default_index_path()
    if (
        _DEFAULT_INDEX_CACHE is not None
        and _DEFAULT_INDEX_CACHE_PATH == selected_path
        and not refresh
    ):
        return _DEFAULT_INDEX_CACHE

    _DEFAULT_INDEX_CACHE_PATH = selected_path
    _DEFAULT_INDEX_CACHE = (
        CommunityIndex.from_path(selected_path)
        if selected_path
        else CommunityIndex.empty()
    )
    return _DEFAULT_INDEX_CACHE


def _stable_beike_key(entry: CommunityEntry) -> str:
    return f"beike::{entry.city}::{entry.district}::{entry.canonical_name}"


def _stable_geo_key(city: str, district: str, business_area: str) -> str:
    return f"geo::{city}::{district}::{business_area}"


def _stable_district_geo_key(city: str, district: str) -> str:
    return f"geo::{city}::{district}"


def _result_from_entry(
    entry: CommunityEntry, source: str, confidence: float, raw_name: str = ""
) -> CommunityResolution:
    return CommunityResolution(
        name=entry.canonical_name,
        source=source,
        confidence=confidence,
        stable_key=_stable_beike_key(entry),
        raw_name=raw_name,
        beike_id=entry.beike_id,
    )


def _looks_like_unstable_address_label(
    raw_name: str, *, city: str, district: str
) -> bool:
    """Return true when an extracted community label is likely a door address.

    Collector-provided community names are useful only when they are reusable
    labels. Full city/district/door strings create one-off keys, so those should
    fall through to address matching or geo anchors instead.
    """
    text = re.sub(r"\s+", "", _clean_text(raw_name))
    if not text:
        return False

    if city and text.startswith(city) and len(text) >= len(city) + 6:
        return True
    if district and text.startswith(district) and len(text) >= len(district) + 8:
        return True

    has_door_detail = bool(re.search(r"\d+(?:号楼|栋|幢|单元|室|层|房)", text))
    location_token_count = sum(
        1
        for token in ("省", "市", "区", "县", "镇", "街道", "路", "街", "巷", "弄")
        if token in text
    )

    if has_door_detail and (len(text) >= 12 or location_token_count >= 1):
        return True
    if len(text) >= 18 and location_token_count >= 2:
        return True

    return False


def _resolve_from_address(
    payload: dict[str, Any],
    *,
    index: CommunityIndex,
    city: str,
    district: str,
    raw_name: str,
) -> CommunityResolution | None:
    address = _first_text(payload, ADDRESS_KEYS)
    address_match = index.match_address(city=city, district=district, address=address)
    if address_match:
        return _result_from_entry(
            address_match, "beike_address", 0.95, raw_name=raw_name
        )
    return None


def _geo_fallback(payload: dict[str, Any]) -> CommunityResolution | None:
    city = _first_text(payload, CITY_KEYS)
    district = _first_text(payload, DISTRICT_KEYS)
    business_area = _first_text(payload, BUSINESS_AREA_KEYS)
    if not (city and district):
        return None
    if not business_area:
        return CommunityResolution(
            name=f"{district}位置片区",
            source="geo_fallback",
            confidence=0.35,
            stable_key=_stable_district_geo_key(city, district),
            raw_name=_first_text(payload, COMMUNITY_KEYS),
        )
    return CommunityResolution(
        name=f"{district}{business_area}位置片区",
        source="geo_fallback",
        confidence=0.45,
        stable_key=_stable_geo_key(city, district, business_area),
        raw_name=_first_text(payload, COMMUNITY_KEYS),
    )


def resolve_community_name(
    payload: dict[str, Any], index: CommunityIndex | None = None
) -> CommunityResolution | None:
    index = index or CommunityIndex.empty()
    city = _first_text(payload, CITY_KEYS)
    district = _first_text(payload, DISTRICT_KEYS)
    raw_name = _first_text(payload, COMMUNITY_KEYS)

    if raw_name:
        match = index.match_name(city=city, district=district, raw_name=raw_name)
        if match:
            entry, kind = match
            source = "beike_exact" if kind == "exact" else "beike_alias"
            confidence = 1.0 if kind == "exact" else 0.98
            return _result_from_entry(entry, source, confidence, raw_name=raw_name)
        address_result = _resolve_from_address(
            payload,
            index=index,
            city=city,
            district=district,
            raw_name=raw_name,
        )
        if address_result:
            return address_result
        if _looks_like_unstable_address_label(raw_name, city=city, district=district):
            return _geo_fallback(payload)
        return CommunityResolution(
            name=raw_name,
            source="collector",
            confidence=0.72,
            stable_key=f"collector::{city}::{district}::{normalize_community_token(raw_name)}",
            raw_name=raw_name,
            beike_id=None,
        )

    address_result = _resolve_from_address(
        payload,
        index=index,
        city=city,
        district=district,
        raw_name="",
    )
    if address_result:
        return address_result

    return _geo_fallback(payload)


def apply_community_resolution(
    item: dict[str, Any], result: CommunityResolution | None
) -> dict[str, Any]:
    if result is None:
        return item

    item["community_name"] = result.name
    item["所属小区"] = result.name
    item["community_name_source"] = result.source
    item["community_name_confidence"] = result.confidence
    item["community_stable_key"] = result.stable_key
    item["community_raw_name"] = result.raw_name
    if result.beike_id:
        item["beike_community_id"] = result.beike_id

    location = item.get("location")
    if isinstance(location, dict):
        location["community_name"] = result.name
    else:
        item["location"] = {"community_name": result.name}

    audit = item.get("audit")
    if isinstance(audit, dict):
        audit["community_name_source"] = result.source
        audit["community_name_confidence"] = result.confidence
        audit["community_stable_key"] = result.stable_key
        audit["community_raw_name"] = result.raw_name
        if result.beike_id:
            audit["beike_community_id"] = result.beike_id

    return item
