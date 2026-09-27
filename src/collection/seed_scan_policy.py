from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit, urlunsplit


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


@dataclass(frozen=True)
class SeedScanJob:
    job_key: str
    province: str
    city: str
    district: str
    location_code: str
    category: str
    source_url_template: str
    metadata: dict[str, Any]


class SeedScanPolicy(Protocol):
    source_platform: str
    requires_location_code: bool
    requires_lease_owner: bool

    def normalize_job(self, job: Mapping[str, Any]) -> SeedScanJob: ...

    def normalize_job_key(self, job_key: str) -> str: ...

    def owns_job(self, job_key: str, metadata: Mapping[str, Any] | None) -> bool: ...

    def build_page_url(
        self,
        *,
        source_url_template: str | None,
        location_code: str,
        category: str,
        sort_key: str,
        st_param: str,
        page: int,
    ) -> str: ...

    def category_order(self, category: str | None) -> tuple[int, str]: ...

    def item_url(self, item_id: str, explicit_url: Any = None) -> str: ...

    def storage_item_id(self, source_item_id: str) -> str: ...


@dataclass(frozen=True)
class GenericSeedScanPolicy:
    """Page-template policy for arbitrary product listing sources."""

    source_platform: str = "generic"
    requires_location_code: bool = False
    requires_lease_owner: bool = True

    def __post_init__(self) -> None:
        platform = _text(self.source_platform)
        if not platform:
            raise ValueError("generic seed source platform is required")
        if len(platform) > 32:
            raise ValueError(
                "generic seed source platform must be at most 32 characters"
            )
        object.__setattr__(self, "source_platform", platform)

    @property
    def job_key_prefix(self) -> str:
        platform = _text(self.source_platform) or "generic"
        slug = re.sub(r"[^a-z0-9]+", "-", platform.lower()).strip("-") or "source"
        namespace = (
            f"{slug[:24]}-{hashlib.sha256(platform.encode('utf-8')).hexdigest()[:8]}"
        )
        return f"source:{namespace}:"

    def normalize_job_key(self, job_key: str) -> str:
        supplied = _text(job_key)
        internal_pattern = rf"{re.escape(self.job_key_prefix)}[0-9a-f]{{40}}"
        if re.fullmatch(internal_pattern, supplied):
            return supplied
        digest = hashlib.sha256((supplied or "default").encode("utf-8")).hexdigest()[
            :40
        ]
        return f"{self.job_key_prefix}{digest}"

    def normalize_job(self, job: Mapping[str, Any]) -> SeedScanJob:
        template = _text(
            job.get("source_url_template") or job.get("url_template") or job.get("url")
        )
        if not template:
            raise ValueError("generic seed scan job requires source_url_template")
        supplied_key = _text(job.get("job_key")) or template
        platform = _text(self.source_platform) or "generic"
        metadata = dict(job.get("metadata") or {})
        metadata.update({"source_platform": platform, "seed_scan_policy": "generic"})
        return SeedScanJob(
            job_key=self.normalize_job_key(supplied_key),
            province=_text(job.get("province")),
            city=_text(job.get("city")),
            district=_text(job.get("district")),
            location_code=(_text(job.get("location_code")) or "source")[:32],
            category=(_text(job.get("category")) or platform)[:32],
            source_url_template=template,
            metadata=metadata,
        )

    def owns_job(self, job_key: str, metadata: Mapping[str, Any] | None) -> bool:
        values = metadata or {}
        return (
            job_key.startswith(self.job_key_prefix)
            and _text(values.get("source_platform"))
            == (_text(self.source_platform) or "generic")
            and _text(values.get("seed_scan_policy")) == "generic"
        )

    def build_page_url(
        self,
        *,
        source_url_template: str | None,
        location_code: str,
        category: str,
        sort_key: str,
        st_param: str,
        page: int,
    ) -> str:
        template = _text(source_url_template)
        if not template:
            raise ValueError("generic seed scan job is missing source_url_template")
        try:
            return template.format(
                location_code=location_code,
                category=category,
                sort_key=sort_key,
                st_param=st_param,
                page=max(int(page or 1), 1),
            )
        except (IndexError, KeyError, ValueError) as exc:
            raise ValueError(f"invalid seed scan URL template: {exc}") from exc

    def category_order(self, category: str | None) -> tuple[int, str]:
        return 10_000, _text(category)

    def item_url(self, item_id: str, explicit_url: Any = None) -> str:
        del item_id
        url = _text(explicit_url)
        if not url:
            raise ValueError("generic seed item requires source URL")
        return f"https:{url}" if url.startswith("//") else url

    def storage_item_id(self, source_item_id: str) -> str:
        normalized = _text(source_item_id)
        if not normalized:
            raise ValueError("generic seed item requires source item ID")
        platform = _text(self.source_platform) or "generic"
        platform_hash = hashlib.sha256(platform.encode("utf-8")).hexdigest()[:8]
        item_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:40]
        return f"src-{platform_hash}-{item_hash}"


@dataclass(frozen=True)
class TaobaoJudicialSeedScanPolicy:
    """Compatibility policy for the existing Taobao judicial seed crawler."""

    source_platform: str = "taobao_sf"
    requires_location_code: bool = True
    requires_lease_owner: bool = False

    @staticmethod
    def _legacy_job_key(job: Mapping[str, Any]) -> str:
        explicit = _text(job.get("job_key"))
        if explicit:
            return explicit
        location_code = _text(job.get("location_code")) or "unknown-location"
        category = _text(job.get("category")) or "unknown-category"
        district = _text(job.get("district")) or _text(job.get("city")) or "scope"
        return f"{location_code}:{category}:{district}"

    def normalize_job_key(self, job_key: str) -> str:
        return _text(job_key)

    def normalize_job(self, job: Mapping[str, Any]) -> SeedScanJob:
        location_code = _text(job.get("location_code"))
        if not location_code:
            raise ValueError("seed scan job requires location_code")
        category = _text(job.get("category")) or "50025969"
        return SeedScanJob(
            job_key=self._legacy_job_key(job),
            province=_text(job.get("province")),
            city=_text(job.get("city")),
            district=_text(job.get("district")),
            location_code=location_code,
            category=category,
            source_url_template=self.build_page_url(
                source_url_template=None,
                location_code=location_code,
                category=category,
                sort_key="{sort_key}",
                st_param="{st_param}",
                page=1,
            ),
            metadata=dict(job.get("metadata") or {}),
        )

    def owns_job(self, job_key: str, metadata: Mapping[str, Any] | None) -> bool:
        values = metadata or {}
        policy_name = _text(values.get("seed_scan_policy"))
        platform = _text(values.get("source_platform"))
        return (
            not job_key.startswith("source:")
            and policy_name in {"", "taobao"}
            and platform
            in {
                "",
                "taobao",
                "taobao_sf",
            }
        )

    def build_page_url(
        self,
        *,
        source_url_template: str | None,
        location_code: str,
        category: str,
        sort_key: str,
        st_param: str,
        page: int,
    ) -> str:
        del source_url_template, sort_key
        return (
            f"https://sf.taobao.com/list/{category}__2.htm"
            f"?location_code={location_code}&st_param={st_param}"
            f"&auction_start_seg=-1&page={max(int(page or 1), 1)}"
        )

    def category_order(self, category: str | None) -> tuple[int, str]:
        normalized = _text(category)
        return {"50025969": 0, "200782003": 1}.get(normalized, 10_000), normalized

    def item_url(self, item_id: str, explicit_url: Any = None) -> str:
        url = _text(explicit_url)
        if url:
            if url.startswith("//"):
                url = f"https:{url}"
            try:
                parsed = urlsplit(url)
            except ValueError:
                return url
            if (parsed.hostname or "").lower() == "sf-item.taobao.com":
                path = parsed.path
                while "//" in path:
                    path = path.replace("//", "/")
                return urlunsplit(
                    (
                        parsed.scheme or "https",
                        parsed.netloc,
                        path,
                        parsed.query,
                        parsed.fragment,
                    )
                )
            return url
        return f"https://sf-item.taobao.com/sf_item/{item_id}.htm"

    def storage_item_id(self, source_item_id: str) -> str:
        normalized = _text(source_item_id)
        if not normalized:
            raise ValueError("seed item requires item ID")
        return normalized


DEFAULT_SEED_SCAN_POLICY = TaobaoJudicialSeedScanPolicy()


def resolve_seed_item_policy(
    *,
    source_platform: object = None,
    explicit_url: object = None,
    policy: SeedScanPolicy | None = None,
    fallback: SeedScanPolicy,
) -> SeedScanPolicy:
    """Select source URL rules for persisted rows without guessing a foreign source."""
    if policy is not None:
        return policy
    platform = (
        ""
        if source_platform is None or isinstance(source_platform, bool)
        else str(source_platform).strip()
    )
    if platform:
        if platform.lower() in {
            "taobao",
            "taobao_judicial",
            "taobao_sf",
            "sf.taobao.com",
        }:
            return TaobaoJudicialSeedScanPolicy()
        return GenericSeedScanPolicy(source_platform=platform)
    url = (
        ""
        if explicit_url is None or isinstance(explicit_url, bool)
        else str(explicit_url).strip()
    )
    if url:
        candidate = f"https:{url}" if url.startswith("//") else url
        try:
            hostname = (urlsplit(candidate).hostname or "").lower()
        except ValueError:
            hostname = ""
        if hostname == "taobao.com" or hostname.endswith(".taobao.com"):
            return TaobaoJudicialSeedScanPolicy()
        return GenericSeedScanPolicy()
    return fallback
