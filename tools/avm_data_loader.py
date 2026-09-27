#!/usr/bin/env python3
"""AVM 原始样本加载辅助函数。

兼容两种常见布局：
1. datas/archive/<year>/*.json
2. datas/*.json
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.collection.archive_records import (
    discover_raw_record_files as discover_raw_record_files,
)
from src.collection.archive_records import (
    load_json_payload as load_json_payload,
)
from src.collection.archive_records import (
    normalize_data_root as normalize_data_root,
)
from src.storage.repository import create_repository_from_env


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def iter_raw_record_rows(
    data_root: Path, prefer_db: bool | None = None
) -> Iterator[dict[str, Any]]:
    use_db = (
        _env_flag("FAPAI_DB_PREFER_ANALYTICS_SOURCE", False)
        if prefer_db is None
        else prefer_db
    )
    if use_db:
        repo = create_repository_from_env()
        if repo.enabled:
            try:
                yielded_any = False
                for row in repo.yield_flat_items():
                    yielded_any = True
                    yield row
                if yielded_any:
                    return
            except Exception:
                pass

    for path in discover_raw_record_files(data_root):
        payload = load_json_payload(path)
        if not isinstance(payload, list):
            continue
        for row in payload:
            if isinstance(row, dict):
                yield row


def _looks_analysis_ready(row: dict[str, Any]) -> bool:
    has_date = bool(row.get("auction_date") or row.get("交易时间"))
    has_area = any(
        row.get(key) not in (None, "", 0, "0")
        for key in ("area_sqm", "建筑面积", "建设面积")
    )
    has_city = bool(row.get("city") or row.get("城市"))
    has_district = bool(row.get("district") or row.get("区"))
    has_price_anchor = any(
        row.get(key) not in (None, "", 0, "0")
        for key in (
            "transaction_price",
            "成交价格",
            "starting_price",
            "起拍价格",
            "actual_paid_price",
            "evaluation_price",
            "市场评估价",
        )
    )
    has_location_precision = any(
        row.get(key) not in (None, "")
        for key in (
            "latitude",
            "纬度",
            "longitude",
            "经度",
            "community_name",
            "所属小区",
            "business_area",
            "最靠近商圈",
        )
    )
    return (
        has_date
        and has_area
        and has_city
        and has_district
        and has_price_anchor
        and has_location_precision
    )


def iter_analysis_ready_rows(
    data_root: Path, prefer_db: bool | None = None
) -> Iterator[dict[str, Any]]:
    use_db = (
        _env_flag("FAPAI_DB_PREFER_ANALYTICS_SOURCE", False)
        if prefer_db is None
        else prefer_db
    )
    if use_db:
        repo = create_repository_from_env()
        if repo.enabled and hasattr(repo, "yield_analysis_ready_flat_items"):
            try:
                yielded_any = False
                for row in repo.yield_analysis_ready_flat_items():
                    yielded_any = True
                    yield row
                if yielded_any:
                    return
            except Exception:
                pass

    for row in iter_raw_record_rows(data_root, prefer_db=False):
        if isinstance(row, dict) and _looks_analysis_ready(row):
            yield row


def load_analysis_ready_rows(
    data_root: Path, prefer_db: bool | None = None
) -> list[dict[str, Any]]:
    return list(iter_analysis_ready_rows(data_root, prefer_db=prefer_db))


def load_recent_analysis_ready_rows(
    data_root: Path, window_days: int, prefer_db: bool | None = None
) -> list[dict[str, Any]]:
    use_db = (
        _env_flag("FAPAI_DB_PREFER_ANALYTICS_SOURCE", False)
        if prefer_db is None
        else prefer_db
    )
    if use_db:
        repo = create_repository_from_env()
        if repo.enabled and hasattr(repo, "yield_analysis_ready_flat_items"):
            try:
                rows = list(repo.yield_analysis_ready_flat_items())
                if rows:
                    return rows
            except Exception:
                pass

    rows = load_analysis_ready_rows(data_root, prefer_db=False)
    dated_rows: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        raw_date = row.get("auction_date") or row.get("交易时间")
        if not raw_date:
            continue
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(str(raw_date), fmt)
                break
            except ValueError:
                continue
        if parsed is not None:
            dated_rows.append((parsed, row))

    if not dated_rows:
        return rows

    max_date = max(dt for dt, _ in dated_rows)
    recent_start = max_date - timedelta(days=window_days - 1)
    return [row for dt, row in dated_rows if dt >= recent_start]


def load_raw_record_rows(
    data_root: Path, prefer_db: bool | None = None
) -> list[dict[str, Any]]:
    return list(iter_raw_record_rows(data_root, prefer_db=prefer_db))


def load_recent_raw_record_rows(
    data_root: Path, window_days: int, prefer_db: bool | None = None
) -> list[dict[str, Any]]:
    use_db = (
        _env_flag("FAPAI_DB_PREFER_CONTROL_PLANE_SOURCE", False)
        if prefer_db is None
        else prefer_db
    )
    if use_db:
        repo = create_repository_from_env()
        if repo.enabled:
            try:
                db_rows = list(repo.yield_recent_flat_items(window_days))
                if db_rows:
                    return db_rows
            except Exception:
                pass

    rows = load_raw_record_rows(data_root, prefer_db=False)
    dated_rows: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        raw_date = row.get("auction_date") or row.get("交易时间")
        if not raw_date:
            continue
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(str(raw_date), fmt)
                break
            except ValueError:
                continue
        if parsed is not None:
            dated_rows.append((parsed, row))

    if not dated_rows:
        return rows

    max_date = max(dt for dt, _ in dated_rows)
    recent_start = max_date - timedelta(days=window_days - 1)
    return [row for dt, row in dated_rows if dt >= recent_start]


def load_sample_raw_record_rows(
    data_root: Path, limit: int, prefer_db: bool | None = None
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    use_db = (
        _env_flag("FAPAI_DB_PREFER_CONTROL_PLANE_SOURCE", False)
        if prefer_db is None
        else prefer_db
    )
    if use_db:
        repo = create_repository_from_env()
        if repo.enabled:
            try:
                db_rows = list(repo.yield_flat_items(limit=limit))
                if db_rows:
                    return db_rows[:limit]
            except Exception:
                pass

    rows: list[dict[str, Any]] = []
    for row in iter_raw_record_rows(data_root, prefer_db=False):
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def load_sample_analysis_ready_rows(
    data_root: Path, limit: int, prefer_db: bool | None = None
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    use_db = (
        _env_flag("FAPAI_DB_PREFER_ANALYTICS_SOURCE", False)
        if prefer_db is None
        else prefer_db
    )
    if use_db:
        repo = create_repository_from_env()
        if repo.enabled and hasattr(repo, "yield_analysis_ready_flat_items"):
            try:
                rows = list(repo.yield_analysis_ready_flat_items(limit=limit))
                if rows:
                    return rows[:limit]
            except Exception:
                pass

    rows: list[dict[str, Any]] = []
    for row in iter_analysis_ready_rows(data_root, prefer_db=False):
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows
