"""Shared imports, constants, and data types for the split runtime."""

from __future__ import annotations

import argparse

import json

import os

import sys

import time

import traceback

from dataclasses import dataclass

from pathlib import Path

from typing import Any, Callable, Iterable, Sequence

from urllib.error import URLError

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_environment import getenv as project_getenv
from src.storage.repository import PropertyRepository, create_repository_from_env
from src.collection.adapter_resolver import collection_adapter_from_env
from src.collection.contracts import CollectionAdapter
from src.collection.pacing import jittered_delay_seconds
from src.collection.seed_list_parser import GenericJsonSeedListParser, SeedListParser, TaobaoSeedListParser
from src.collection.seed_scan_policy import DEFAULT_SEED_SCAN_POLICY, GenericSeedScanPolicy, SeedScanPolicy
from src.collection.runtime_adapter import resolve_record_adapter

from tools.internal_api_http import fetch_json, post_json

from tools.live_batch_smoke import (
    CdpEndpointUnavailableError,
    DEFAULT_API_BASE_URL,
    DEFAULT_CDP_ENDPOINT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_USER_AGENT,
    build_http,
    captcha_solver_enabled,
    export_cookies,
    fetch_list_page,
    resolve_runtime_user_agent,
    write_json,
)

DEFAULT_SEED_SORTS = (
    "sort_0:0:默认排序,"
    "sort_3:3:价格由高到低,"
    "bid_desc:2:出价次数由高到低,"
    "end_time_soon:1:结拍时间由近到远,"
    "sort_4:4:排序4,"
    "sort_5:5:排序5"
)

DEFAULT_SEED_JOB_KEY = "guangdong-guangzhou-nansha-50025969"

DEFAULT_SEED_LOCATION_CODE = "440115"

DEFAULT_SEED_CATEGORY = "50025969"

STATUS_UNAVAILABLE_RETRY_ATTEMPTS = 3

STATUS_UNAVAILABLE_RETRY_SLEEP_SECONDS = 1.0

DEFAULT_AUTH_PROBE_INTERVAL_SECONDS = 900

@dataclass(frozen=True)
class SeedSortSpec:
    sort_key: str
    st_param: str
    sort_name: str
    sort_order: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "sort_key": self.sort_key,
            "st_param": self.st_param,
            "sort_name": self.sort_name,
            "sort_order": self.sort_order,
        }

@dataclass(frozen=True)
class SeedScanJobSpec:
    job_key: str
    province: str
    city: str
    district: str
    location_code: str
    category: str
    sort_specs: tuple[SeedSortSpec, ...]
    max_page: int
    source_url_template: str = ""

    def as_job_dict(self) -> dict[str, Any]:
        payload = {
            "job_key": self.job_key,
            "province": self.province,
            "city": self.city,
            "district": self.district,
            "location_code": self.location_code,
            "category": self.category,
        }
        if self.source_url_template:
            payload["source_url_template"] = self.source_url_template
        return payload

@dataclass(frozen=True)
class SeedCollectorConfig:
    job_key: str
    province: str
    city: str
    district: str
    location_code: str
    category: str
    sort_specs: tuple[SeedSortSpec, ...]
    max_page: int
    cdp_endpoint: str
    output_dir: Path
    worker_id: str
    lease_seconds: int = 120
    loop_interval_seconds: int = 1800
    active_loop_interval_seconds: int | None = None
    max_runs: int | None = None
    pages_per_run: int = 10
    page_delay_seconds: float = 8.0
    pacing_jitter_ratio: float = 0.35
    solver_enabled: bool = False
    manual_challenge_reporting: bool = False
    api_base_url: str = ""
    seed_jobs: tuple[SeedScanJobSpec, ...] = ()
    parallel_sorts: bool = False
    failure_cooldown_threshold: int = 0
    failure_cooldown_seconds: int = 0
    auth_probe_interval_seconds: int = DEFAULT_AUTH_PROBE_INTERVAL_SECONDS
    source_url_template: str = ""
    seed_scan_policy: SeedScanPolicy | None = None
    collection_adapter: CollectionAdapter | None = None
    breadth_first: bool = False

    def __post_init__(self) -> None:
        if self.collection_adapter is None:
            return
        adapter_policy = self.collection_adapter.seed_scan_policy
        if self.seed_scan_policy is not None and (
            self.seed_scan_policy.source_platform != adapter_policy.source_platform
        ):
            raise ValueError("seed scan policy does not match the collection adapter")
        if self.seed_scan_policy is None:
            object.__setattr__(self, "seed_scan_policy", adapter_policy)

SeedRuntimeContextFactory = Callable[[], Any]

SeedProgressEmitFunc = Callable[[dict[str, Any]], None]

__all__ = (
    "project_getenv",
    'argparse',
    'json',
    'os',
    'sys',
    'time',
    'traceback',
    'dataclass',
    'Path',
    'Any',
    'Callable',
    'Iterable',
    'Sequence',
    'URLError',
    'parse_qsl',
    'urlencode',
    'urlsplit',
    'urlunsplit',
    'Request',
    'urlopen',
    'REPO_ROOT',
    'PropertyRepository',
    'create_repository_from_env',
    'collection_adapter_from_env',
    'CollectionAdapter',
    'jittered_delay_seconds',
    'GenericJsonSeedListParser',
    'SeedListParser',
    'TaobaoSeedListParser',
    'DEFAULT_SEED_SCAN_POLICY',
    'GenericSeedScanPolicy',
    'SeedScanPolicy',
    'resolve_record_adapter',
    'fetch_json',
    'post_json',
    'CdpEndpointUnavailableError',
    'DEFAULT_API_BASE_URL',
    'DEFAULT_CDP_ENDPOINT',
    'DEFAULT_OUTPUT_DIR',
    'DEFAULT_USER_AGENT',
    'build_http',
    'captcha_solver_enabled',
    'export_cookies',
    'fetch_list_page',
    'resolve_runtime_user_agent',
    'write_json',
    'DEFAULT_SEED_SORTS',
    'DEFAULT_SEED_JOB_KEY',
    'DEFAULT_SEED_LOCATION_CODE',
    'DEFAULT_SEED_CATEGORY',
    'STATUS_UNAVAILABLE_RETRY_ATTEMPTS',
    'STATUS_UNAVAILABLE_RETRY_SLEEP_SECONDS',
    'DEFAULT_AUTH_PROBE_INTERVAL_SECONDS',
    'SeedSortSpec',
    'SeedScanJobSpec',
    'SeedCollectorConfig',
    'SeedRuntimeContextFactory',
    'SeedProgressEmitFunc',
)
