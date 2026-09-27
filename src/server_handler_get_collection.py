from __future__ import annotations

import logging
import sys
import time  # noqa: F401 - direct-module analysis clock
from typing import cast

from .analysis_read_handlers import AnalysisReadHost, bind_analysis_reads
from .auth_recovery_read_handlers import RecoveryReadHost, bind_recovery_reads
from .collection_read_handlers import CollectionReadHost, bind_collection_reads
from .collection_status_handler import CollectionStatusHost, bind_collection_status
from .detail_dispatch_handlers import DetailDispatchHost, bind_detail_dispatch
from .manual_review_read_handlers import ReviewReadHost, bind_review_reads
from .report_job_handlers import ReportHost, bind_report_jobs
from .server_context import (
    AVM_SERVICE,  # noqa: F401 - direct-module host dependency
    DATA_DIR,  # noqa: F401 - direct-module host dependency
    DB_REPOSITORY,  # noqa: F401 - direct-module host dependency
    DISPATCH_COOLDOWN_SECONDS,  # noqa: F401 - direct-module host dependency
    NAS_AUTH_RECOVERY,  # noqa: F401 - direct-module host dependency
    filter_manual_review_receipt_operations,  # noqa: F401 - direct-module host dependency
    list_manual_review_receipts,  # noqa: F401 - direct-module host dependency
    llm_helper,  # noqa: F401 - direct-module host dependency
    load_manual_review_control_plane_backup_repairs,  # noqa: F401 - direct-module host dependency
    load_manual_review_control_plane_integrity_history,  # noqa: F401 - direct-module host dependency
    load_manual_review_receipt_operations,  # noqa: F401 - direct-module host dependency
)

logger = logging.getLogger(__name__)

_collection_reads = bind_collection_reads(
    cast(CollectionReadHost, sys.modules[__name__])
)
_get_collection_index = _collection_reads._get_collection_index
_get_collection_asset = _collection_reads._get_collection_asset
_get_collection_overview = _collection_reads._get_collection_overview
_get_collection_items = _collection_reads._get_collection_items
_get_collection_regions = _collection_reads._get_collection_regions
_get_collection_item = _collection_reads._get_collection_item

_review_reads = bind_review_reads(cast(ReviewReadHost, sys.modules[__name__]))
_get_manual_review_receipts = _review_reads._get_manual_review_receipts
_get_manual_review_jobs = _review_reads._get_manual_review_jobs
_get_manual_review_operations = _review_reads._get_manual_review_operations
_get_manual_review_control_status = _review_reads._get_manual_review_control_status
_get_manual_review_backup_repairs = _review_reads._get_manual_review_backup_repairs
_get_manual_review_integrity_history = (
    _review_reads._get_manual_review_integrity_history
)

_recovery_reads = bind_recovery_reads(cast(RecoveryReadHost, sys.modules[__name__]))
_get_auth_recovery = _recovery_reads._get_auth_recovery
_get_auth_recovery_snapshot = _recovery_reads._get_auth_recovery_snapshot

_get_status = bind_collection_status(
    cast(CollectionStatusHost, sys.modules[__name__])
)._get_status

_post_detail_next_task = bind_detail_dispatch(
    cast(DetailDispatchHost, sys.modules[__name__])
)._post_detail_next_task

_analysis_reads = bind_analysis_reads(cast(AnalysisReadHost, sys.modules[__name__]))
_get_analysis_prediction = _analysis_reads._get_analysis_prediction
_get_analysis_health = _analysis_reads._get_analysis_health
_get_collection_template = _analysis_reads._get_collection_template

_report_jobs = bind_report_jobs(cast(ReportHost, sys.modules[__name__]))
_post_drift_report = _report_jobs._post_drift_report
_post_release_gate = _report_jobs._post_release_gate
_post_recent_gap_audit = _report_jobs._post_recent_gap_audit

__all__ = [  # noqa: RUF022 - preserve legacy export ordering
    "_get_collection_index",
    "_get_collection_asset",
    "_get_collection_overview",
    "_get_collection_items",
    "_get_collection_regions",
    "_get_collection_item",
    "_get_manual_review_receipts",
    "_get_manual_review_jobs",
    "_get_manual_review_operations",
    "_get_manual_review_control_status",
    "_get_manual_review_backup_repairs",
    "_get_manual_review_integrity_history",
    "_get_auth_recovery",
    "_get_auth_recovery_snapshot",
    "_get_status",
    "_post_detail_next_task",
    "_get_analysis_prediction",
    "_get_analysis_health",
    "_get_collection_template",
    "_post_drift_report",
    "_post_release_gate",
    "_post_recent_gap_audit",
]
