"""Shared imports, constants, and data types for the split runtime."""

from __future__ import annotations

import argparse

import datetime

import json

import math

import os

import re

import shutil

import sys

import time

import traceback

from dataclasses import dataclass

from pathlib import Path

from typing import Any, Callable, Sequence

from urllib.error import URLError

from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_environment import getenv as project_getenv
from src.storage.repository import PropertyRepository, create_repository_from_env
from src.collection.adapter_resolver import collection_adapter_from_env
from src.collection.contracts import CollectionAdapter
from src.collection.pacing import jittered_delay_seconds
from src.collection.runtime_adapter import resolve_record_adapter

from tools.internal_api_http import fetch_json

from tools.live_batch_smoke import (
    CdpEndpointUnavailableError,
    DEFAULT_CDP_ENDPOINT,
    DEFAULT_OUTPUT_DIR,
    LiveSmokeConfig,
    analyze_raw_item,
    build_http,
    captcha_solver_enabled,
    export_cookies,
    is_challenge_page,
    load_open_browser_pages,
    load_json,
    preflight_llm_backend,
    process_item,
    write_json,
)

@dataclass(frozen=True)
class DetailWorkerConfig:
    output_dir: Path
    cdp_endpoint: str
    target_success: int
    max_attempts: int
    worker_id: str
    do_risk: bool
    lease_seconds: int = 900
    item_max_attempts: int = 3
    failure_cooldown_seconds: int = 0
    success_delay_seconds: float = 6.0
    failure_delay_seconds: float = 15.0
    pacing_jitter_ratio: float = 0.35
    challenge_cooldown_seconds: int = 900
    loop_interval_seconds: int = 900
    active_loop_interval_seconds: int | None = None
    max_runs: int | None = None
    llm_preflight_enabled: bool = False
    llm_preflight_timeout_seconds: float = 15.0
    llm_preflight_attempts: int = 3
    llm_preflight_retry_delay_seconds: float = 2.0
    solver_enabled: bool = False
    api_base_url: str = ""
    raw_only: bool = False
    analysis_only: bool = False
    manual_challenge_reporting: bool = False
    detail_archive_root: Path | None = None
    collection_adapter: CollectionAdapter | None = None

ProcessItemFunc = Callable[[Any, dict[str, Any], dict[str, tuple[str, str]], Any], dict[str, Any]]

AnalyzeItemFunc = Callable[..., dict[str, Any]]

RuntimeContext = tuple[Any, dict[str, tuple[str, str]]]

RuntimeContextFactory = Callable[[], RuntimeContext]

ProgressEmitFunc = Callable[[dict[str, Any]], None]

STATUS_UNAVAILABLE_RETRY_ATTEMPTS = 3

STATUS_UNAVAILABLE_RETRY_SLEEP_SECONDS = 1.0

DETAIL_ITEM_ID_RE = re.compile(r"/sf_item/(\d+)\.htm", re.IGNORECASE)

__all__ = (
    "project_getenv",
    'argparse',
    'datetime',
    'json',
    'math',
    'os',
    're',
    'shutil',
    'sys',
    'time',
    'traceback',
    'dataclass',
    'Path',
    'Any',
    'Callable',
    'Sequence',
    'URLError',
    'urlopen',
    'REPO_ROOT',
    'PropertyRepository',
    'create_repository_from_env',
    'collection_adapter_from_env',
    'CollectionAdapter',
    'jittered_delay_seconds',
    'resolve_record_adapter',
    'fetch_json',
    'CdpEndpointUnavailableError',
    'DEFAULT_CDP_ENDPOINT',
    'DEFAULT_OUTPUT_DIR',
    'LiveSmokeConfig',
    'analyze_raw_item',
    'build_http',
    'captcha_solver_enabled',
    'export_cookies',
    'is_challenge_page',
    'load_open_browser_pages',
    'load_json',
    'preflight_llm_backend',
    'process_item',
    'write_json',
    'DetailWorkerConfig',
    'ProcessItemFunc',
    'AnalyzeItemFunc',
    'RuntimeContext',
    'RuntimeContextFactory',
    'ProgressEmitFunc',
    'STATUS_UNAVAILABLE_RETRY_ATTEMPTS',
    'STATUS_UNAVAILABLE_RETRY_SLEEP_SECONDS',
    'DETAIL_ITEM_ID_RE',
)
