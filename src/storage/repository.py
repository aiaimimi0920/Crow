from __future__ import annotations

from src.collection.contracts import CollectionAdapter, Record
from src.collection.seed_scan_policy import SeedScanPolicy
from src.collection.stage_state import derive_collection_state, derive_stage_state
from src.project_environment import getenv as project_getenv

from .repository_collection import RepositoryCollectionMixin
from .repository_context import DatabaseSettings, _env_flag
from .repository_core import RepositoryCoreMixin
from .repository_detail_analysis import RepositoryDetailAnalysisMixin
from .repository_detail_claim import RepositoryDetailClaimMixin
from .repository_flat_payload import RepositoryFlatPayloadMixin
from .repository_flat_query import RepositoryFlatQueryMixin
from .repository_geo import RepositoryGeoMixin
from .repository_manual_review import RepositoryManualReviewMixin
from .repository_observer_items import RepositoryObserverItemsMixin
from .repository_observer_regions import RepositoryObserverRegionsMixin
from .repository_readiness import RepositoryReadinessMixin
from .repository_search import RepositorySearchMixin
from .repository_seed_items import RepositorySeedItemsMixin
from .repository_seed_scan_jobs import RepositorySeedScanJobsMixin
from .repository_seed_scan_pages import RepositorySeedScanPagesMixin
from .repository_task_events import RepositoryTaskEventsMixin


class CollectionRepository(
    RepositoryCoreMixin,
    RepositoryFlatPayloadMixin,
    RepositoryFlatQueryMixin,
    RepositoryGeoMixin,
    RepositoryCollectionMixin,
    RepositoryReadinessMixin,
    RepositoryTaskEventsMixin,
    RepositorySearchMixin,
    RepositorySeedScanJobsMixin,
    RepositorySeedScanPagesMixin,
    RepositorySeedItemsMixin,
    RepositoryDetailClaimMixin,
    RepositoryDetailAnalysisMixin,
    RepositoryObserverRegionsMixin,
    RepositoryObserverItemsMixin,
    RepositoryManualReviewMixin,
):
    """Collection writes use source rules without running postprocessing."""

    def __init__(self, settings: DatabaseSettings, *, adapter: CollectionAdapter):
        super().__init__(settings)
        self.adapter = adapter

    def _build_collection_record(self, item: Record) -> Record:
        return self.adapter.build_storage_record(item)

    _derive_stage_state = staticmethod(derive_collection_state)

    def _build_search_task_url(
        self, location_code: str, category: str, sort_param: str, page: int
    ) -> str:
        if not self.adapter.bootstraps_legacy_search_tasks:
            raise ValueError("collection search tasks require an explicit source URL")
        payload = self.adapter.search_task_policy.claim_payload(
            task_key=self._search_task_key(location_code, category, sort_param),
            location_code=location_code,
            category=category,
            sort_param=sort_param,
            page=page,
            source_url=None,
        )
        return str(payload["url"])


class PropertyRepository(CollectionRepository):
    """Legacy callers retain their analysis projection until C2 migrates startup."""

    def __init__(self, settings: DatabaseSettings):
        from src.collection.adapters.taobao_judicial import TaobaoJudicialAuctionAdapter

        super().__init__(settings, adapter=TaobaoJudicialAuctionAdapter())

    _derive_stage_state = staticmethod(derive_stage_state)

    @staticmethod
    def _seed_item_url(
        item_id: str, explicit_url: object = None, policy: SeedScanPolicy | None = None
    ) -> str:
        from src.collection.seed_scan_policy import DEFAULT_SEED_SCAN_POLICY

        return (policy or DEFAULT_SEED_SCAN_POLICY).item_url(item_id, explicit_url)


def database_settings_from_env() -> DatabaseSettings:
    return DatabaseSettings(
        url=project_getenv("CROW_DB_URL", "").strip(),
        echo=_env_flag("CROW_DB_ECHO", False),
        enable_postgis=_env_flag("CROW_DB_ENABLE_POSTGIS", False),
        auto_create=_env_flag("CROW_DB_AUTO_CREATE", False),
        enabled=_env_flag("CROW_DB_ENABLED", True),
    )


def create_repository_from_env() -> PropertyRepository:
    return PropertyRepository(settings=database_settings_from_env())


def create_collection_repository_from_env(
    *,
    adapter: CollectionAdapter,
) -> CollectionRepository:
    return CollectionRepository(database_settings_from_env(), adapter=adapter)


__all__ = [
    "CollectionRepository",
    "DatabaseSettings",
    "PropertyRepository",
    "create_repository_from_env",
    "create_collection_repository_from_env",
]
