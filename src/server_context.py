import http.server
import socketserver
import json
import os
import base64
import datetime
import hashlib
import glob
import mimetypes
import math
import hmac
from pathlib import Path
import threading
import tempfile
import time
import re
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .collection_control_state import CHALLENGE_SCOPES, new_scope_state
from .collection_runtime_index import CollectionRuntimeIndex
from .runtime_state import RuntimeState
from .server_runtime_paths import (
    DATA_DIR,
    NAS_AUTH_RECOVERY_STATE_PATH,
    NAS_AUTH_RECOVERY_TOKEN_FILE,
)
from .solver_request_payload import (
    _build_solver_request,
    _normalize_challenge_scope,
    _normalize_solver_cdp_endpoint,
    _normalize_solver_target_url,
    _real_taobao_auto_solver_enabled,
    _runtime_env_flag,
    _solver_target_requires_manual_only,
)
from .utc_timestamps import (
    _as_utc_timestamp,
    _parse_utc_timestamp,
    _utc_now,
    _utc_timestamp_leq,
)

from src import llm_helper
from src.avm_config import AVM_CONFIG_MANAGER
from src.avm_config import DEFAULT_AVM_CONFIG
from src.avm_config import get_effective_alert_threshold
from src.captcha_solver import CaptchaSolver

# Import Captcha Solver
solver = CaptchaSolver()


from src.avm.service import AVMService
from src.avm.pipeline import AVMPipelineManager, AVMPipelineConfig
from src.avm.collection_template import sync_collection_record
from src.avm.alert_policy import build_alert_blockers
from src.collection import (
    DetailCollectionService,
    SeedCollectionService,
    collection_adapter_from_env,
)
from src.detail_artifacts import (
    extract_detail_artifacts as _shared_extract_detail_artifacts,
    get_detail_archive_path as _shared_get_detail_archive_path,
)
from src.storage import create_repository_from_env
from src.nas_auth_recovery import NasAuthRecoveryCoordinator
from tools.analysis_stage_planner import (
    load_action_effectiveness_snapshot,
    load_manual_review_receipt_snapshot,
    load_optimization_loop_progress_snapshot,
    load_recent_gap_audit_snapshot,
    recommend_analysis_stage_actions,
    summarize_action_effectiveness_snapshot,
    summarize_manual_review_backlog,
    summarize_manual_review_reentry_application_summary,
    summarize_manual_review_receipt_snapshot,
    summarize_operator_action_surface,
    summarize_operator_overview,
    summarize_recoverability_snapshot,
    summarize_scheduler_feedback_snapshot,
)
from tools.manual_review_receipt_audit import (
    append_manual_review_receipt_operation,
    filter_manual_review_receipt_operations,
    load_manual_review_receipt_operations,
    summarize_manual_review_receipt_operations_snapshot,
)
from tools.manual_review_receipt_jobs import (
    load_manual_review_receipt_jobs,
    summarize_manual_review_receipt_jobs_snapshot,
)
from tools.manual_review_receipt_store import (
    delete_manual_review_receipt,
    list_manual_review_receipts,
    upsert_manual_review_receipt,
)
from tools.backfill_manual_review_control_plane_to_db import (
    describe_manual_review_control_plane_backup,
    describe_manual_review_control_plane_storage,
    load_manual_review_control_plane_backup_repairs,
    load_manual_review_control_plane_integrity_history,
    record_manual_review_control_plane_integrity,
    summarize_manual_review_control_plane_guidance,
    summarize_manual_review_control_plane_integrity,
    summarize_manual_review_control_plane_backup_repairs,
    summarize_manual_review_control_plane_integrity_history,
    summarize_manual_review_control_plane_stability,
)
from tools.apply_avm_calibration_patch import (
    apply_command_chain_next_action_policy,
    apply_avm_calibration_patch,
    normalize_calibration_targets_payload,
    resolve_command_chain_artifacts,
    summarize_bundle_command_summary,
    summarize_patch_follow_up_command,
    summarize_patch_command_chain,
    summarize_patch_next_action,
    summarize_patch_next_action_command,
    summarize_patch_risk,
)
from tools.run_recent_enrich_maintenance import run_recent_enrich_maintenance

PORT = 8001
BATCH_SIZE = 8  # User Configurable Concurrency
DISPATCH_COOLDOWN_SECONDS = 20  # Task redispatch cooldown (aggressive profile)
# Global Thread Pool for AI tasks (Limit 32 to prevent API overload)
executor = ThreadPoolExecutor(max_workers=32)
REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_DESKTOP_DIST = REPO_ROOT / "collector-desktop" / "dist"
AVM_DIR = os.path.join(DATA_DIR, "avm")
AVM_ALERTS_PATH = os.path.join(AVM_DIR, "alerts.json")

DB_REPOSITORY = create_repository_from_env()
AVM_SERVICE = AVMService(data_dir=DATA_DIR, repository=DB_REPOSITORY)
AVM_PIPELINE = AVMPipelineManager(data_dir=DATA_DIR)

RUNTIME = RuntimeState()
CHALLENGE_FORCE_RESET_SECONDS = max(
    1.0,
    float(os.getenv("FAPAI_CHALLENGE_FORCE_RESET_SECONDS", "900")),
)
SOLVER_AUTH_REPORT_GRACE_SECONDS = max(
    0.0,
    float(os.getenv("FAPAI_SOLVER_AUTH_REPORT_GRACE_SECONDS", "90")),
)
SOLVER_DETAIL_PROGRESS_GRACE_SECONDS = max(
    SOLVER_AUTH_REPORT_GRACE_SECONDS,
    float(os.getenv("FAPAI_SOLVER_DETAIL_PROGRESS_GRACE_SECONDS", "180")),
)
SOLVER_DETAIL_PROGRESS_GRACE_MIN_ITEMS = max(
    1,
    int(os.getenv("FAPAI_SOLVER_DETAIL_PROGRESS_GRACE_MIN_ITEMS", "1")),
)
SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS = max(
    0.0,
    float(os.getenv("FAPAI_SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS", "180")),
)
NAS_AUTH_RECOVERY_POLL_SECONDS = max(
    5.0,
    float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_POLL_SECONDS", "60")),
)
NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS = max(
    60.0,
    float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS", "300")),
)
NAS_AUTH_RECOVERY = NasAuthRecoveryCoordinator(
    NAS_AUTH_RECOVERY_STATE_PATH,
    enabled=str(os.getenv("FAPAI_NAS_AUTH_RECOVERY_ENABLED", "0")).strip().lower()
    in {"1", "true", "yes", "on"},
    stall_seconds=float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_STALL_SECONDS", "1800")),
    pc1_timeout_seconds=float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_PC1_TIMEOUT_SECONDS", "1800")),
    pc2_timeout_seconds=float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_PC2_TIMEOUT_SECONDS", "600")),
    verify_timeout_seconds=float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_VERIFY_TIMEOUT_SECONDS", "600")),
    cooldown_seconds=float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_COOLDOWN_SECONDS", "1800")),
)


DEFAULT_MARGIN_THRESHOLD = 0.15
MALIGNANT_RISK_LABELS = {
    "is_haunted": "疑似凶宅/刑事案件",
    "is_occupied": "房屋疑似被占用未腾空",
    "has_long_lease": "存在长租约风险",
    "is_fractional_share": "标的为部分产权",
    "tax_is_company_owned": "企业产权潜在高税费",
}

RISK_ALIAS_KEYS = (
    "community_name",
    "build_year",
    "total_floors",
    "floor_level",
    "has_elevator",
    "orientation",
    "land_right_type",
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "tax_burden",
    "is_haunted",
    "housing_type",
    "has_keys",
    "property_fee_owed",
    "special_school_tag",
    "layout",
    "is_restricted_purchase",
    "includes_parking",
    "is_fractional_share",
    "tax_is_company_owned",
    "has_lease_before_mortgage",
    "extraction_confidence",
    "evidence_span",
    "evidence_source",
    "extraction_version",
)

__all__ = [name for name in globals() if not name.startswith("__")]
