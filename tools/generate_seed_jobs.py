from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_CATEGORIES = ("50025969", "200782003")
DEFAULT_SORTS = (
    {"sort_key": "sort_0", "st_param": "0", "sort_name": "默认排序", "sort_order": 0},
    {"sort_key": "sort_3", "st_param": "3", "sort_name": "价格由高到低", "sort_order": 1},
    {"sort_key": "bid_desc", "st_param": "2", "sort_name": "出价次数由高到低", "sort_order": 2},
    {"sort_key": "end_time_soon", "st_param": "1", "sort_name": "结拍时间由近到远", "sort_order": 3},
    {"sort_key": "sort_4", "st_param": "4", "sort_name": "排序4", "sort_order": 4},
    {"sort_key": "sort_5", "st_param": "5", "sort_name": "排序5", "sort_order": 5},
)


@dataclass(frozen=True)
class LocationEntry:
    code: str
    province: str
    city: str
    district: str
    source: str = "all_locations"


def _clean_text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, list):
        raise ValueError("locations file must contain a JSON array")
    return [item for item in decoded if isinstance(item, dict)]


def _walk_locations(nodes: Iterable[dict[str, Any]], path_names: tuple[str, ...] = ()) -> list[LocationEntry]:
    entries: list[LocationEntry] = []
    for node in nodes:
        code = _clean_text(node.get("code"))
        name = _clean_text(node.get("name") or node.get("label"))
        next_path = (*path_names, name) if name else path_names
        if len(code) == 6 and code.isdigit():
            province = next_path[0] if len(next_path) >= 1 else ""
            city = next_path[1] if len(next_path) >= 2 else ""
            district = next_path[2] if len(next_path) >= 3 else ""
            entries.append(LocationEntry(code=code, province=province, city=city, district=district))
        children = node.get("children")
        if isinstance(children, list):
            entries.extend(_walk_locations([child for child in children if isinstance(child, dict)], next_path))
    return entries


def _dedupe_location_entries(entries: Iterable[LocationEntry]) -> list[LocationEntry]:
    unique: list[LocationEntry] = []
    index_by_code: dict[str, int] = {}
    for entry in entries:
        if entry.code in index_by_code:
            unique[index_by_code[entry.code]] = entry
            continue
        index_by_code[entry.code] = len(unique)
        unique.append(entry)
    return unique


def load_location_entries(locations_path: str | Path) -> list[LocationEntry]:
    entries = _walk_locations(_load_json_array(Path(locations_path)))
    return _dedupe_location_entries(entries)


def load_taobao_location_entries(taobao_locations_path: str | Path | None) -> list[LocationEntry]:
    if not taobao_locations_path:
        return []
    path = Path(taobao_locations_path)
    if not path.exists():
        return []
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(decoded, dict):
        raw_entries = decoded.get("locations") or decoded.get("entries") or []
    else:
        raw_entries = decoded
    if not isinstance(raw_entries, list):
        raise ValueError("taobao locations file must contain a JSON array or an object with a locations array")
    entries: list[LocationEntry] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        code = _clean_text(item.get("location_code") or item.get("code"))
        if not code.isdigit() or len(code) < 4:
            continue
        entries.append(
            LocationEntry(
                code=code,
                province=_clean_text(item.get("province")),
                city=_clean_text(item.get("city")),
                district=_clean_text(item.get("district") or item.get("name") or item.get("label")),
                source="taobao_sf_location_overrides",
            )
        )
    return _dedupe_location_entries(entries)


def load_taobao_replace_admin_provinces(taobao_locations_path: str | Path | None) -> set[str]:
    if not taobao_locations_path:
        return set()
    path = Path(taobao_locations_path)
    if not path.exists():
        return set()
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        return set()
    raw_values = decoded.get("replace_admin_provinces") or []
    if not isinstance(raw_values, list):
        return set()
    return {value for value in (_clean_text(item) for item in raw_values) if value}


def load_merged_location_entries(
    locations_path: str | Path,
    taobao_locations_path: str | Path | None = None,
) -> list[LocationEntry]:
    entries = load_location_entries(locations_path)
    replace_admin_provinces = load_taobao_replace_admin_provinces(taobao_locations_path)
    if replace_admin_provinces:
        entries = [entry for entry in entries if entry.province not in replace_admin_provinces]
    taobao_entries = load_taobao_location_entries(taobao_locations_path)
    if taobao_entries:
        entries = _dedupe_location_entries([*entries, *taobao_entries])
    return entries


def build_seed_jobs(
    *,
    locations_path: str | Path,
    taobao_locations_path: str | Path | None = None,
    categories: Sequence[str] = DEFAULT_CATEGORIES,
    max_page: int = 83,
    sorts: Sequence[dict[str, Any]] = DEFAULT_SORTS,
) -> list[dict[str, Any]]:
    clean_categories = tuple(category for category in (_clean_text(value) for value in categories) if category)
    if not clean_categories:
        raise ValueError("at least one category is required")
    clean_max_page = max(int(max_page), 1)
    jobs: list[dict[str, Any]] = []
    for location in load_merged_location_entries(locations_path, taobao_locations_path):
        for category in clean_categories:
            jobs.append(
                {
                    "job_key": f"{location.code}-{category}",
                    "province": location.province,
                    "city": location.city,
                    "district": location.district,
                    "location_code": location.code,
                    "category": category,
                    "max_page": clean_max_page,
                    "sorts": [dict(sort) for sort in sorts],
                    "metadata": {"location_source": location.source},
                }
            )
    return jobs


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate full Crow Taobao/SF seed jobs from all_locations.json.")
    parser.add_argument("--locations-file", type=Path, default=Path("datas") / "all_locations.json")
    parser.add_argument("--taobao-locations-file", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--categories", nargs="+", default=list(DEFAULT_CATEGORIES))
    parser.add_argument("--max-page", type=int, default=83)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    jobs = build_seed_jobs(
        locations_path=args.locations_file,
        taobao_locations_path=args.taobao_locations_file,
        categories=tuple(args.categories),
        max_page=int(args.max_page),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "job_count": len(jobs),
                "location_count": len(load_merged_location_entries(args.locations_file, args.taobao_locations_file)),
                "taobao_location_override_count": len(load_taobao_location_entries(args.taobao_locations_file)),
                "categories": list(args.categories),
                "max_page": int(args.max_page),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
