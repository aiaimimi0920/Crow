from __future__ import annotations

import logging
import sys
from typing import cast

from .detail_ingest_handlers import DetailIngestHost, bind_detail_ingest
from .evaluation_handlers import EvaluationHost, bind_evaluations
from .location_catalog_handler import LocationCatalogHost, bind_location_catalog
from .manual_review_write_contracts import ReviewWriteHost
from .manual_review_write_handlers import bind_review_writes
from .pipeline_submission_handlers import PipelineHost, bind_pipeline_submissions
from .seed_task_handlers import SeedTaskHost, bind_seed_tasks
from .server_context import (
    AVM_SERVICE,  # noqa: F401 - direct-module native host dependency
    DATA_DIR,  # noqa: F401 - direct-module native host dependency
    DB_REPOSITORY,  # noqa: F401 - direct-module native host dependency
    RUNTIME,  # noqa: F401 - direct-module native host dependency
    AVMPipelineConfig,  # noqa: F401 - direct-module native host dependency
    append_manual_review_receipt_operation,  # noqa: F401 - native host dependency
    list_manual_review_receipts,  # noqa: F401 - native host dependency
    llm_helper,  # noqa: F401 - direct-module native host dependency
    run_recent_enrich_maintenance,  # noqa: F401 - native host dependency
    upsert_manual_review_receipt,  # noqa: F401 - native host dependency
)

logger = logging.getLogger(__name__)

_review_writes = bind_review_writes(cast(ReviewWriteHost, sys.modules[__name__]))
_post_manual_review_receipt = _review_writes._post_manual_review_receipt
_prepare_manual_review_receipt_submission = (
    _review_writes._prepare_manual_review_receipt_submission
)

_pipeline_submissions = bind_pipeline_submissions(
    cast(PipelineHost, sys.modules[__name__])
)
_resolve_pipeline_data_dir = _pipeline_submissions._resolve_pipeline_data_dir
_post_analysis_run = _pipeline_submissions._post_analysis_run
_post_detail_maintenance = _pipeline_submissions._post_detail_maintenance
_post_fetch_missing_detail_archives = (
    _pipeline_submissions._post_fetch_missing_detail_archives
)
_post_archive_detail_replay = _pipeline_submissions._post_archive_detail_replay
_post_start_all_subtasks = _pipeline_submissions._post_start_all_subtasks
_post_run_all_subtasks_sync = _pipeline_submissions._post_run_all_subtasks_sync

_evaluations = bind_evaluations(cast(EvaluationHost, sys.modules[__name__]))
_read_execution_mode = _evaluations._read_execution_mode
_post_analysis_evaluate = _evaluations._post_analysis_evaluate
_post_infer_location = _evaluations._post_infer_location

_post_save_locations = bind_location_catalog(
    cast(LocationCatalogHost, sys.modules[__name__])
)._post_save_locations

_detail_ingest = bind_detail_ingest(cast(DetailIngestHost, sys.modules[__name__]))
_post_area_result = _detail_ingest._post_area_result
_post_approve_area = _detail_ingest._post_approve_area

_post_seed_batch = bind_seed_tasks(
    cast(SeedTaskHost, sys.modules[__name__])
)._post_seed_batch

__all__ = [  # noqa: RUF022 - preserve legacy export ordering
    "_resolve_pipeline_data_dir",
    "_read_execution_mode",
    "_post_manual_review_receipt",
    "_prepare_manual_review_receipt_submission",
    "_post_analysis_run",
    "_post_analysis_evaluate",
    "_post_detail_maintenance",
    "_post_fetch_missing_detail_archives",
    "_post_archive_detail_replay",
    "_post_start_all_subtasks",
    "_post_run_all_subtasks_sync",
    "_post_save_locations",
    "_post_area_result",
    "_post_infer_location",
    "_post_approve_area",
    "_post_seed_batch",
]
