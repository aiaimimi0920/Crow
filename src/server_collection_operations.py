from __future__ import annotations

import logging
import json
import os
import re
import time
import datetime
from typing import Any
from typing import cast
import sys
from .collection_file_runtime import CollectionFileHost, CollectionFileRuntime
from .solver_retry_loop import RetryLoopHost, SolverRetryLoop
from .screen_alert_store import ScreenAlertHost, ScreenAlertStore
from .screen_result_summary import ScreenResultSummary, ScreenSummaryHost
from .collection_working_items import CollectionWorkingItems, WorkingItemHost
from .collection.adapters.auction_prices import AuctionPriceHost, AuctionPricePolicy
from .collection.adapters.auction_risks import AuctionRiskHost, AuctionRiskPolicy
from .collection.adapters.auction_record_patch import (
    FLAT_OVERRIDE_ALIASES as _FLAT_OVERRIDE_ALIAS_MAP,
    AuctionPatchHost,
    AuctionRecordPatch,
)
from .collection_service_operations import (
    CollectionServiceHost,
    CollectionServiceOperations,
)

from .server_context import (
    AVM_ALERTS_PATH,
    AVM_DIR,
    DATA_DIR,
    DB_REPOSITORY,
    DetailCollectionService,
    MALIGNANT_RISK_LABELS,
    RISK_ALIAS_KEYS,
    RUNTIME,
    SeedCollectionService,
    collection_adapter_from_env,
    executor,
    sync_collection_record,
    _runtime_env_flag,
)
from .server_http_responses import _json_payload_type_name

logger = logging.getLogger(__name__)


_working_items = CollectionWorkingItems(cast(WorkingItemHost, sys.modules[__name__]))
_collection_runtime_index = _working_items._collection_runtime_index
_evict_runtime_item = _working_items._evict_runtime_item
_get_working_item = _working_items._get_working_item


def _prefer_db_task_reads() -> bool:
    return DB_REPOSITORY.enabled and _runtime_env_flag(
        "FAPAI_DB_PREFER_RUNTIME_INDEX", True
    )


_record_patch = AuctionRecordPatch(cast(AuctionPatchHost, sys.modules[__name__]))
_reset_structured_sections_for_resync = (
    _record_patch._reset_structured_sections_for_resync
)
_apply_flat_override_patch = _record_patch._apply_flat_override_patch


manual_solver_retry_thread = SolverRetryLoop(
    cast(RetryLoopHost, sys.modules[__name__])
).manual_solver_retry_thread

JOBS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jobs"
)


_service_operations = CollectionServiceOperations(
    cast(CollectionServiceHost, sys.modules[__name__])
)
_seed_collection_service = _service_operations._seed_collection_service
_detail_collection_service = _service_operations._detail_collection_service
build_sniff_stub = _service_operations.build_sniff_stub
handle_seed_batch_submission = _service_operations.handle_seed_batch_submission


submit_task = CollectionFileRuntime(
    cast(CollectionFileHost, sys.modules[__name__])
).submit_task


_auction_prices = AuctionPricePolicy(cast(AuctionPriceHost, sys.modules[__name__]))
parse_price = _auction_prices.parse_price
get_starting_price = _auction_prices.get_starting_price
get_predicted_price = _auction_prices.get_predicted_price
compute_margin = _auction_prices.compute_margin
_safe_int = _auction_prices._safe_int


_auction_risks = AuctionRiskPolicy(cast(AuctionRiskHost, sys.modules[__name__]))
_get_risk_payload = _auction_risks._get_risk_payload
_risk_value = _auction_risks._risk_value
sync_avm_risk_aliases = _auction_risks.sync_avm_risk_aliases
extract_risk_signals = _auction_risks.extract_risk_signals
build_avm_result = _auction_risks.build_avm_result


_screen_summary = ScreenResultSummary(cast(ScreenSummaryHost, sys.modules[__name__]))
_prediction_confidence_bucket = _screen_summary._prediction_confidence_bucket
summarize_screen_results = _screen_summary.summarize_screen_results
write_avm_alerts = ScreenAlertStore(
    cast(ScreenAlertHost, sys.modules[__name__])
).write_avm_alerts


__all__ = [
    "_json_payload_type_name",
    "_evict_runtime_item",
    "_reset_structured_sections_for_resync",
    "_FLAT_OVERRIDE_ALIAS_MAP",
    "_apply_flat_override_patch",
    "_get_working_item",
    "manual_solver_retry_thread",
    "JOBS_DIR",
    "_seed_collection_service",
    "_detail_collection_service",
    "submit_task",
    "parse_price",
    "get_starting_price",
    "get_predicted_price",
    "compute_margin",
    "_safe_int",
    "_get_risk_payload",
    "_risk_value",
    "sync_avm_risk_aliases",
    "build_sniff_stub",
    "handle_seed_batch_submission",
    "extract_risk_signals",
    "build_avm_result",
    "_prediction_confidence_bucket",
    "summarize_screen_results",
    "write_avm_alerts",
]
