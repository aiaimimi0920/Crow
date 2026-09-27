"""Single composition entrypoint for explicit native server owners."""

from types import ModuleType
from typing import cast

from .analysis_read_handlers import AnalysisReadHost, bind_analysis_reads
from .auth_command_handlers import AuthCommandHost, bind_auth_commands
from .auth_completion_binding import AuthCompletionHost, bind_auth_completion
from .auth_cookie_binding import AuthCookieHost, bind_auth_cookie
from .auth_recovery_binding import AuthRecoveryHost, bind_auth_recovery
from .auth_recovery_read_handlers import RecoveryReadHost, bind_recovery_reads
from .auth_recovery_transition_handler import (
    RecoveryTransitionHost,
    bind_recovery_transitions,
)
from .captcha_report_handler import CaptchaReportHost, bind_captcha_reports
from .collection.adapters.auction_prices import AuctionPriceHost, AuctionPricePolicy
from .collection.adapters.auction_record_patch import (
    AuctionPatchHost,
    AuctionRecordPatch,
)
from .collection.adapters.auction_risks import AuctionRiskHost, AuctionRiskPolicy
from .collection_archive_binding import CollectionArchiveHost, bind_collection_archives
from .collection_control_binding import CollectionControlHost, bind_collection_control
from .collection_database_writes import (
    CollectionWriteHost,
    bind_collection_database_writes,
)
from .collection_file_runtime import CollectionFileHost, CollectionFileRuntime
from .collection_index_bootstrap import CollectionIndexBootstrap, CollectionIndexHost
from .collection_read_handlers import CollectionReadHost, bind_collection_reads
from .collection_service_operations import (
    CollectionServiceHost,
    CollectionServiceOperations,
)
from .collection_startup import CollectionStartup, CollectionStartupHost
from .collection_status_handler import CollectionStatusHost, bind_collection_status
from .collection_working_items import CollectionWorkingItems, WorkingItemHost
from .detail_dispatch_handlers import DetailDispatchHost, bind_detail_dispatch
from .detail_ingest_handlers import DetailIngestHost, bind_detail_ingest
from .evaluation_handlers import EvaluationHost, bind_evaluations
from .location_catalog_handler import LocationCatalogHost, bind_location_catalog
from .manual_review_read_handlers import ReviewReadHost, bind_review_reads
from .manual_review_write_contracts import ReviewWriteHost
from .manual_review_write_handlers import bind_review_writes
from .observer_command_handlers import ObserverCommandHost, bind_observer_commands
from .pipeline_submission_handlers import PipelineHost, bind_pipeline_submissions
from .report_job_handlers import ReportHost, bind_report_jobs
from .screen_alert_store import ScreenAlertHost, ScreenAlertStore
from .screen_handlers import ScreenHost, bind_screen
from .screen_result_summary import ScreenResultSummary, ScreenSummaryHost
from .seed_task_handlers import SeedTaskHost, bind_seed_tasks
from .server_handler_compatibility import (
    HandlerCompatibilityHost,
    bind_handler_compatibility,
)
from .solver_dispatch_binding import SolverDispatchHost, bind_solver_dispatch
from .solver_execution_guard import SolverExecutionGuard, SolverExecutionHost
from .solver_retry_loop import RetryLoopHost, SolverRetryLoop
from .solver_retry_monitor_binding import RetryMonitorHost, bind_solver_retry_monitor
from .solver_run_binding import bind_solver_run
from .solver_run_contracts import SolverRunHost
from .solver_state_binding import SolverStateHost, bind_solver_state
from .task_read_handlers import TaskReadHost, bind_task_reads
from .upload_handler import UploadHost, bind_uploads


def bind_native_server_owners(host: ModuleType) -> tuple[object, ...]:
    return (
        *bind_auth_recovery(cast(AuthRecoveryHost, host)),
        *bind_auth_cookie(cast(AuthCookieHost, host)),
        *bind_auth_completion(cast(AuthCompletionHost, host)),
        *bind_collection_control(cast(CollectionControlHost, host)),
        bind_solver_state(cast(SolverStateHost, host)),
        bind_solver_dispatch(cast(SolverDispatchHost, host)),
        bind_solver_retry_monitor(cast(RetryMonitorHost, host)),
        *bind_collection_archives(cast(CollectionArchiveHost, host)),
        bind_collection_database_writes(cast(CollectionWriteHost, host)),
        CollectionStartup(cast(CollectionStartupHost, host)),
        CollectionIndexBootstrap(cast(CollectionIndexHost, host)),
        CollectionFileRuntime(cast(CollectionFileHost, host)),
        SolverRetryLoop(cast(RetryLoopHost, host)),
        CollectionWorkingItems(cast(WorkingItemHost, host)),
        CollectionServiceOperations(cast(CollectionServiceHost, host)),
        AuctionPricePolicy(cast(AuctionPriceHost, host)),
        AuctionRecordPatch(cast(AuctionPatchHost, host)),
        AuctionRiskPolicy(cast(AuctionRiskHost, host)),
        ScreenResultSummary(cast(ScreenSummaryHost, host)),
        ScreenAlertStore(cast(ScreenAlertHost, host)),
    )


def bind_native_handler_owners(host: ModuleType) -> tuple[object, ...]:
    return (
        SolverExecutionGuard(cast(SolverExecutionHost, host)),
        bind_solver_run(cast(SolverRunHost, host)),
        bind_handler_compatibility(cast(HandlerCompatibilityHost, host)),
        bind_detail_dispatch(cast(DetailDispatchHost, host)),
        bind_seed_tasks(cast(SeedTaskHost, host)),
        bind_recovery_transitions(cast(RecoveryTransitionHost, host)),
        bind_observer_commands(cast(ObserverCommandHost, host)),
        bind_auth_commands(cast(AuthCommandHost, host)),
        bind_task_reads(cast(TaskReadHost, host)),
        bind_collection_reads(cast(CollectionReadHost, host)),
        bind_recovery_reads(cast(RecoveryReadHost, host)),
        bind_review_reads(cast(ReviewReadHost, host)),
        bind_analysis_reads(cast(AnalysisReadHost, host)),
        bind_report_jobs(cast(ReportHost, host)),
        bind_collection_status(cast(CollectionStatusHost, host)),
        bind_captcha_reports(cast(CaptchaReportHost, host)),
        bind_uploads(cast(UploadHost, host)),
        bind_detail_ingest(cast(DetailIngestHost, host)),
        bind_screen(cast(ScreenHost, host)),
        bind_pipeline_submissions(cast(PipelineHost, host)),
        bind_evaluations(cast(EvaluationHost, host)),
        bind_review_writes(cast(ReviewWriteHost, host)),
        bind_location_catalog(cast(LocationCatalogHost, host)),
    )
