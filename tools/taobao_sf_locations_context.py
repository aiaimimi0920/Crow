"""Shared imports, constants, and data types for the split tool."""

from __future__ import annotations

import argparse

import json

import os

import re

import sys

import time

from dataclasses import dataclass

from datetime import datetime, timezone

from pathlib import Path

from typing import Any, Iterable, Sequence

from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_environment import getenv as project_getenv

from tools import generate_seed_jobs  # noqa: E402

DEFAULT_CATEGORY = "50025969"

DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9223"

DEFAULT_OUTPUT = Path("datas") / "taobao_sf_locations_observed.json"

DEFAULT_OVERRIDES = Path("datas") / "taobao_sf_location_overrides.json"

DEFAULT_START_URL = "https://sf.taobao.com/list/{category}__2.htm?auction_source=0&st_param=-1&auction_start_seg=-1"

SCHEMA_VERSION = "taobao_sf_locations_v1"

LOCATION_OPTION_IGNORE_LABELS = {
    "",
    "不限",
    "全省",
    "全市",
    "全部",
}

CATEGORY_LABELS = {
    "住宅用房",
    "商业用房",
    "工业用房",
    "其他用房",
    "机动车",
    "航空交通",
    "船舶",
    "其他交通",
    "股权",
    "债权",
    "林权",
    "矿权",
    "土地",
    "工程",
    "海域",
    "机器设备",
    "资产",
    "无形资产",
    "古玩字画",
    "珠宝首饰",
    "其他",
}

DIRECT_MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}

CHALLENGE_MARKERS = (
    "_____tmd_____/punish",
    "x5secdata=",
    "霸下通用 web 页面-验证码",
    "请完成验证",
    "安全验证",
    "RGV587_ERROR",
)

@dataclass(frozen=True)
class LocationOption:
    label: str
    href: str
    level: str
    location_code: str | None = None

@dataclass(frozen=True)
class LocationFilterOptions:
    provinces: list[LocationOption]
    cities: list[LocationOption]
    districts: list[LocationOption]
    source_url: str = ""

@dataclass(frozen=True)
class TaobaoLocationEntry:
    province: str
    city: str
    district: str
    location_code: str
    source_url: str = ""

    def to_override_dict(self) -> dict[str, str]:
        return {
            "province": self.province,
            "city": self.city,
            "district": self.district,
            "location_code": self.location_code,
        }

    def to_observed_dict(self) -> dict[str, str]:
        payload = self.to_override_dict()
        if self.source_url:
            payload["source_url"] = self.source_url
        return payload

class AdminLocationIndex:
    def __init__(self, all_locations_path: str | Path):
        self.province_by_short_name: dict[str, str] = {}
        self.city_by_province_and_short_name: dict[tuple[str, str], str] = {}
        self._load(all_locations_path)

    def _load(self, all_locations_path: str | Path) -> None:
        payload = read_json(all_locations_path, default=[])
        if not isinstance(payload, list):
            return
        for province_node in payload:
            if not isinstance(province_node, dict):
                continue
            province = clean_text(province_node.get("name"))
            if not province:
                continue
            self.province_by_short_name.setdefault(short_region_name(province), province)
            children = province_node.get("children")
            if not isinstance(children, list):
                continue
            for city_node in children:
                if not isinstance(city_node, dict):
                    continue
                city = clean_text(city_node.get("name"))
                if city:
                    self.city_by_province_and_short_name.setdefault((province, short_region_name(city)), city)

__all__ = (
    "project_getenv",
    'argparse',
    'json',
    'os',
    're',
    'sys',
    'time',
    'dataclass',
    'datetime',
    'timezone',
    'Path',
    'Any',
    'Iterable',
    'Sequence',
    'parse_qs',
    'urljoin',
    'urlparse',
    'BeautifulSoup',
    'REPO_ROOT',
    'generate_seed_jobs',
    'DEFAULT_CATEGORY',
    'DEFAULT_CDP_ENDPOINT',
    'DEFAULT_OUTPUT',
    'DEFAULT_OVERRIDES',
    'DEFAULT_START_URL',
    'SCHEMA_VERSION',
    'LOCATION_OPTION_IGNORE_LABELS',
    'CATEGORY_LABELS',
    'DIRECT_MUNICIPALITIES',
    'CHALLENGE_MARKERS',
    'LocationOption',
    'LocationFilterOptions',
    'TaobaoLocationEntry',
    'AdminLocationIndex',
)
