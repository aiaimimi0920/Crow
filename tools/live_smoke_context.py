from __future__ import annotations

import argparse

import concurrent.futures

import datetime

import hashlib

import json

import os

import re

import sys

import time

import traceback

from dataclasses import dataclass

from pathlib import Path

from typing import Any, Iterable, Mapping

from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import requests

from bs4 import BeautifulSoup

from src.collection.contracts import CollectionAdapter, DetailExtractor
from src.collection.pacing import jittered_delay_seconds

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_environment import EnvironmentAliasConflict, getenv as project_getenv
from src.project_data_paths import resolve_project_data_root
from tools.safe_exception_diagnostics import safe_exception_details, safe_exception_text, safe_exception_traceback

DEFAULT_OUTPUT_DIR = Path("output/live_batch_smoke")

DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9223"

DEFAULT_CDP_CONNECT_TIMEOUT_MS = 120000

DEFAULT_LIST_BROWSER_NAV_TIMEOUT_MS = 10000

DEFAULT_LIST_BROWSER_RECOVERY_MAX_ATTEMPTS = 2

DEFAULT_LIST_BROWSER_RECOVERY_WAIT_SECONDS = 2.0

DEFAULT_DETAIL_BROWSER_READY_TIMEOUT_MS = 8000

DEFAULT_DETAIL_BROWSER_POLL_INTERVAL_MS = 250

DEFAULT_RESUME_STATE_FILENAME = "resume_state.json"

DEFAULT_LIST_ST_PARAMS = ("2", "1", "0", "3", "4", "5")

DEFAULT_TARGET_URL = (
    "https://sf.taobao.com/list/50025969__2.htm"
    "?location_code=110101&st_param=2&auction_start_seg=-1&page=1"
)

DEFAULT_API_BASE_URL = project_getenv("CROW_API_BASE_URL", "http://127.0.0.1:8001/api")

DEFAULT_CDP_PAGE_TARGET_LIMIT = 12

DEFAULT_CDP_HTTP_TIMEOUT_SECONDS = 3.0

DEFAULT_CDP_RECONNECT_ATTEMPTS = 3

DEFAULT_CDP_RECONNECT_BACKOFF_SECONDS = 0.5

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
)

AREA_FOLLOWUP_NEXT_ATTEMPTS = [
    "announcement_attachment",
    "appraisal_report_attachment",
    "detail_page_images_ocr",
    "external_property_or_community_index",
]

RESUME_SCHEMA_VERSION = "live_batch_resume_state_v1"

RESUME_COMPLETED_STATUS = "completed"

TRUE_VALUES = {"1", "true", "yes", "y", "on"}

CAPTCHA_SOLVER_ENV_NAMES = (
    "FAPAI_CAPTCHA_SOLVER_ENABLED",
    "FAPAI_SOLVER_ENABLED",
    "SOLVER_ENABLED",
    "solver_enabled",
)

MOBILE_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

SERVICE_PHONE_RE = re.compile(r"(?<!\d)400[-\s]?\d{3}[-\s]?\d{4}(?!\d)")

LANDLINE_PHONE_RE = re.compile(r"(?<!\d)0\d{2,3}[-\s]?\d{7,8}(?!\d)")

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

CONTACT_FIELD_RE = re.compile(r"(联系方式|联系人|咨询电话|电话|手机)[:：]?\s*[^\s<]{1,32}")

class CdpEndpointUnavailableError(RuntimeError):
    def __init__(self, cdp_endpoint: str, operation: str, cause: BaseException):
        self.cdp_endpoint = str(cdp_endpoint or "")
        self.operation = str(operation or "")
        self.cause = cause
        super().__init__("CDP endpoint unavailable")


class DetailChallengeError(RuntimeError):
    def __init__(self, operation: str, challenge_url: str = ""):
        self.operation = str(operation or "detail request")
        self.challenge_url = str(challenge_url or "")
        super().__init__(f"{self.operation} returned anti-bot challenge")


@dataclass(frozen=True)
class LiveSmokeConfig:
    output_dir: Path
    cdp_endpoint: str
    target_url: str
    target_success: int
    max_attempts: int
    do_risk: bool
    resume_state_path: Path | None = None
    resume_enabled: bool = True
    list_st_params: tuple[str, ...] = ()
    list_location_codes: tuple[str, ...] = ()
    list_categories: tuple[str, ...] = ()
    list_max_pages: int = 1
    list_stop_on_empty: bool = True
    list_delay_seconds: float = 8.0
    llm_preflight_enabled: bool = False
    llm_preflight_timeout_seconds: float = 15.0
    raw_only: bool = False
    collection_adapter: CollectionAdapter | None = None
    detail_extractor: DetailExtractor | None = None
    success_delay_seconds: float = 6.0
    failure_delay_seconds: float = 15.0
    pacing_jitter_ratio: float = 0.35
    challenge_cooldown_seconds: float = 900.0

__all__ = [name for name in globals() if not name.startswith("__")]
