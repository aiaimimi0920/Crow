"""Construct the collection resources without importing the legacy server context."""

from __future__ import annotations

import datetime
import glob
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from urllib.request import urlopen

from . import llm_helper
from .captcha_solver import CaptchaSolver
from .collection import DetailCollectionService, SeedCollectionService
from .collection.adapter_resolver import collection_adapter_from_env
from .collection.adapters.auction_record_patch import FLAT_OVERRIDE_ALIASES
from .collection.adapters.auction_risk_fields import (
    MALIGNANT_RISK_LABELS,
    RISK_ALIAS_KEYS,
)
from .collection.contracts import CollectionAdapter
from .collection_control_state import CHALLENGE_SCOPES
from .collection_index_loader import load_collection_index
from .detail_artifacts import extract_detail_artifacts, get_detail_archive_path
from .nas_auth_recovery import NasAuthRecoveryCoordinator
from .project_data_paths import resolve_collection_data_dir
from .runtime_json import load_json_file
from .runtime_state import RuntimeState
from .solver_request_payload import (
    _build_solver_request,
    _normalize_challenge_scope,
    _normalize_solver_cdp_endpoint,
    _normalize_solver_target_url,
    _real_taobao_auto_solver_enabled,
    _runtime_env_flag,
    _solver_target_requires_manual_only,
)
from .storage.repository import (
    CollectionRepository,
    create_collection_repository_from_env,
)
from .utc_timestamps import (
    _as_utc_timestamp,
    _parse_utc_timestamp,
    _utc_now,
    _utc_timestamp_leq,
)


def create_collection_host(
    *,
    data_root: str | Path | None = None,
    repository: CollectionRepository | None = None,
    adapter: CollectionAdapter | None = None,
) -> ModuleType:
    root = Path(__file__).resolve().parents[1]
    data = resolve_collection_data_dir(root, data_root)
    selected = adapter or (
        repository.adapter
        if repository is not None
        else collection_adapter_from_env(default="taobao_judicial")
    )
    if (
        repository is not None
        and repository.adapter.source_platform != selected.source_platform
    ):
        raise ValueError(
            "Collection repository and runtime must use the same source adapter"
        )
    host = ModuleType("crow_collection_application")
    resources: dict[str, object] = {
        "DATA_DIR": str(data),
        "REPO_ROOT": root,
        "JOBS_DIR": str(root / "jobs"),
        "COLLECTOR_DESKTOP_DIST": root / "collector-desktop" / "dist",
        "COLLECTION_ADAPTER": selected,
        "DB_REPOSITORY": repository
        or create_collection_repository_from_env(adapter=selected),
        "RUNTIME": RuntimeState(),
        "STOP_EVENT": threading.Event(),
        "executor": ThreadPoolExecutor(
            max_workers=32, thread_name_prefix="crow-detail"
        ),
        "solver": CaptchaSolver(),
        "CaptchaSolver": CaptchaSolver,
        "DetailCollectionService": DetailCollectionService,
        "SeedCollectionService": SeedCollectionService,
        "collection_adapter_from_env": lambda **_options: selected,
        "sync_collection_record": selected.sync_record,
        "CHALLENGE_SCOPES": CHALLENGE_SCOPES,
        "RISK_ALIAS_KEYS": RISK_ALIAS_KEYS,
        "MALIGNANT_RISK_LABELS": MALIGNANT_RISK_LABELS,
        "_FLAT_OVERRIDE_ALIAS_MAP": FLAT_OVERRIDE_ALIASES,
        "urlopen": urlopen,
        "BATCH_SIZE": 8,
        "DISPATCH_COOLDOWN_SECONDS": 20,
        "load_collection_index": load_collection_index,
        "load_json_file": load_json_file,
        "_build_solver_request": _build_solver_request,
        "_normalize_challenge_scope": _normalize_challenge_scope,
        "_normalize_solver_cdp_endpoint": _normalize_solver_cdp_endpoint,
        "_normalize_solver_target_url": _normalize_solver_target_url,
        "_real_taobao_auto_solver_enabled": _real_taobao_auto_solver_enabled,
        "_runtime_env_flag": _runtime_env_flag,
        "_solver_target_requires_manual_only": _solver_target_requires_manual_only,
        "_utc_now": _utc_now,
        "_as_utc_timestamp": _as_utc_timestamp,
        "_parse_utc_timestamp": _parse_utc_timestamp,
        "_utc_timestamp_leq": _utc_timestamp_leq,
        "_shared_extract_detail_artifacts": extract_detail_artifacts,
        "_shared_get_detail_archive_path": get_detail_archive_path,
        "llm_helper": llm_helper,
        "logger": logging.getLogger("crow.collection"),
        "datetime": datetime,
        "glob": glob,
        "json": json,
        "os": os,
        "threading": threading,
        "time": time,
    }
    for name, (default, minimum) in {
        "CHALLENGE_FORCE_RESET_SECONDS": (900, 1),
        "SOLVER_AUTH_REPORT_GRACE_SECONDS": (90, 0),
        "SOLVER_DETAIL_PROGRESS_GRACE_SECONDS": (180, 0),
        "SOLVER_DETAIL_PROGRESS_GRACE_MIN_ITEMS": (1, 1),
        "SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS": (180, 0),
        "NAS_AUTH_RECOVERY_POLL_SECONDS": (60, 5),
        "NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS": (300, 60),
    }.items():
        resources[name] = max(minimum, float(os.getenv("FAPAI_" + name, str(default))))
    resources["SOLVER_DETAIL_PROGRESS_GRACE_SECONDS"] = max(
        float(str(resources["SOLVER_AUTH_REPORT_GRACE_SECONDS"])),
        float(str(resources["SOLVER_DETAIL_PROGRESS_GRACE_SECONDS"])),
    )
    state = Path(os.getenv("FAPAI_SOLVER_STATE_DIR") or data)
    resources["NAS_AUTH_RECOVERY"] = NasAuthRecoveryCoordinator(
        Path(
            os.getenv("FAPAI_NAS_AUTH_RECOVERY_STATE_PATH")
            or state / "nas-auth-recovery.json"
        ),
        enabled=os.getenv("FAPAI_NAS_AUTH_RECOVERY_ENABLED", "0").strip().lower()
        in {"1", "true", "yes", "on"},
        stall_seconds=float(os.getenv("FAPAI_NAS_AUTH_RECOVERY_STALL_SECONDS", "1800")),
        pc1_timeout_seconds=float(
            os.getenv("FAPAI_NAS_AUTH_RECOVERY_PC1_TIMEOUT_SECONDS", "1800")
        ),
        pc2_timeout_seconds=float(
            os.getenv("FAPAI_NAS_AUTH_RECOVERY_PC2_TIMEOUT_SECONDS", "600")
        ),
        verify_timeout_seconds=float(
            os.getenv("FAPAI_NAS_AUTH_RECOVERY_VERIFY_TIMEOUT_SECONDS", "600")
        ),
        cooldown_seconds=float(
            os.getenv("FAPAI_NAS_AUTH_RECOVERY_COOLDOWN_SECONDS", "1800")
        ),
    )
    vars(host).update(resources)
    return host
