from __future__ import annotations

import datetime, json, os, sys, time, traceback, uuid

import multiprocessing

from pathlib import Path

from typing import Any

from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.captcha_solver import CaptchaSolver

from tools.internal_api_http import fetch_json, post_json

from tools.pc2_auth_recovery import process_nas_auth_recovery_once

from tools.pc2_solver_config import (
    AUTH_COMPLETE_PENDING_MAX_SECONDS,
    AUTH_COMPLETE_REQUEST_ATTEMPTS,
    AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS,
    AUTH_COMPLETE_REQUEST_TIMEOUT_SECONDS,
    AUTH_COMPLETE_RETRY_BASE_SECONDS,
    AUTH_COMPLETE_RETRY_MAX_SECONDS,
    AUTH_RECOVERY_MARKER_PATH,
    AUTH_RECOVERY_SNAPSHOT_PATH,
    AUTH_RECOVERY_TOKEN_PATH,
    DEFAULT_API_BASE_URL,
    DEFAULT_CDP_ENDPOINT,
    DEFAULT_DRAG_PROFILE_VARIANTS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_POLL_SECONDS,
    POST_AUTH_CDP_PROBE_GRACE_SECONDS,
    RECENT_HEALTHY_AUTH_MAX_AGE_SECONDS,
    SOLVER_EXECUTION_TIMEOUT_SECONDS,
    SOLVER_HEARTBEAT_PATH,
    SOLVER_TERMINATE_GRACE_SECONDS,
)

__all__ = [name for name in globals() if not name.startswith("__")]
