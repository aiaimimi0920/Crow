#!/usr/bin/env python3
"""Backfill missing listing coordinates from a geocoding provider."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_environment import getenv as project_getenv
from tools.geocode_client import AmapGeocoder, GeocodeProviderError, GeocodeQuotaExceeded
from tools.geocode_targets import build_target_key


def _load_missing_coordinate_targets(repo: Any) -> list[dict[str, Any]]:
    from sqlalchemy import or_, select
    from src.storage.models import PropertyListing

    repo.initialize()
    statement = (
        select(
            PropertyListing.item_id,
            PropertyListing.city,
            PropertyListing.district,
            PropertyListing.community_name,
        )
        .where(
            PropertyListing.is_deleted.is_(False),
            PropertyListing.city.is_not(None),
            PropertyListing.city != "",
            PropertyListing.community_name.is_not(None),
            PropertyListing.community_name != "",
            or_(
                PropertyListing.latitude.is_(None),
                PropertyListing.longitude.is_(None),
            ),
        )
        .order_by(PropertyListing.item_id.asc())
    )

    grouped: dict[str, dict[str, Any]] = {}
    with repo.session_factory() as session:
        for item_id, city, district, community_name in session.execute(statement):
            key = build_target_key(
                city=city,
                district=district,
                community_name=community_name,
            )
            if not key:
                continue
            target = grouped.setdefault(
                key,
                {
                    "key": key,
                    "query": key,
                    "item_ids": [],
                },
            )
            target["item_ids"].append(str(item_id))

    targets = list(grouped.values())
    targets.sort(key=lambda target: (-len(target["item_ids"]), target["key"]))
    return targets


def _load_progress(progress_path: Path | None) -> dict[str, Any]:
    if progress_path is None or not progress_path.exists():
        return {}
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid geocode progress file {progress_path}: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"geocode progress file must contain an object: {progress_path}")
    return payload


def _write_progress(progress_path: Path | None, progress: Mapping[str, Any]) -> None:
    if progress_path is None:
        return
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = progress_path.with_name(f".{progress_path.name}.tmp")
    temporary_path.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(progress_path)


def _coordinate_values(result: Mapping[str, Any]) -> tuple[float, float]:
    try:
        latitude = float(result["latitude"])
        longitude = float(result["longitude"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("geocode result is missing numeric latitude/longitude") from error
    if not (3.5 <= latitude <= 53.6 and 73.5 <= longitude <= 135.1):
        raise ValueError("geocode result is outside the supported China coordinate range")
    return latitude, longitude


def _write_target_coordinates(
    repo: Any,
    *,
    item_ids: Sequence[str],
    result: Mapping[str, Any],
) -> int:
    from sqlalchemy import or_, select
    from src.storage.models import PropertyListing

    latitude, longitude = _coordinate_values(result)
    provider = str(result.get("provider") or "geocoder").strip().lower()
    coordinate_source = f"{provider}_geocode_wgs84"

    with repo.session_factory.begin() as session:
        statement = select(PropertyListing).where(
            PropertyListing.item_id.in_(list(item_ids)),
            PropertyListing.is_deleted.is_(False),
            or_(
                PropertyListing.latitude.is_(None),
                PropertyListing.longitude.is_(None),
            ),
        )
        listings = list(session.scalars(statement))
        for listing in listings:
            listing.latitude = latitude
            listing.longitude = longitude
            listing.coordinate_source = coordinate_source
        session.flush()
        for listing in listings:
            repo._apply_postgis_point(session, listing.item_id, latitude, longitude)
    return len(listings)


def backfill_coordinates_from_geocoder(
    repo: Any,
    geocoder: Any,
    *,
    dry_run: bool = False,
    progress_path: Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Geocode unique communities and write each result to all matching rows."""
    targets = _load_missing_coordinate_targets(repo)
    if limit is not None and limit > 0:
        targets = targets[:limit]
    progress = _load_progress(progress_path)
    summary = {
        "dry_run": bool(dry_run),
        "targets_total": len(targets),
        "targets_attempted": 0,
        "targets_written": 0,
        "rows_written": 0,
        "targets_not_found": 0,
        "targets_from_progress": 0,
        "targets_failed": 0,
        "stopped_by_quota": False,
    }

    for target in targets:
        query = target["query"]
        summary["targets_attempted"] += 1
        if query in progress:
            result = progress[query]
            summary["targets_from_progress"] += 1
        else:
            try:
                result = geocoder.geocode(query)
            except GeocodeQuotaExceeded:
                summary["stopped_by_quota"] = True
                break
            except GeocodeProviderError:
                summary["targets_failed"] += 1
                continue
            progress[query] = result
            _write_progress(progress_path, progress)

        if result is None:
            summary["targets_not_found"] += 1
            continue
        if not isinstance(result, Mapping):
            summary["targets_failed"] += 1
            continue
        try:
            _coordinate_values(result)
        except ValueError:
            summary["targets_failed"] += 1
            continue
        if dry_run:
            continue

        rows_written = _write_target_coordinates(
            repo,
            item_ids=target["item_ids"],
            result=result,
        )
        if rows_written:
            summary["targets_written"] += 1
            summary["rows_written"] += rows_written

    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill missing listing coordinates with Amap geocoding")
    parser.add_argument(
        "--progress-path",
        type=Path,
        default=Path("datas/avm/amap_geocode_progress.json"),
        help="JSON checkpoint used to resume without repeating provider calls",
    )
    parser.add_argument("--limit", type=int, default=0, help="maximum unique communities to process; 0 means all")
    parser.add_argument("--dry-run", action="store_true", help="geocode and checkpoint targets without writing the database")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    from src.storage.repository import create_repository_from_env

    args = parse_args(argv)
    api_key = project_getenv("CROW_AMAP_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("CROW_AMAP_API_KEY (legacy FAPAI_AMAP_API_KEY) must be set")
    repo = create_repository_from_env()
    if not repo.enabled:
        raise SystemExit("CROW_DB_URL (legacy FAPAI_DB_URL) must be set")
    summary = backfill_coordinates_from_geocoder(
        repo,
        AmapGeocoder(api_key=api_key),
        dry_run=args.dry_run,
        progress_path=args.progress_path,
        limit=args.limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if summary["stopped_by_quota"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
