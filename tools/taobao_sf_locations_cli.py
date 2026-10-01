"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.taobao_sf_locations_context import *


def _parse_csv(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    values: list[str] = []
    for chunk in str(raw).replace(";", ",").split(","):
        value = clean_text(chunk)
        if value and value not in values:
            values.append(value)
    return tuple(values)


def cmd_crawl(args: argparse.Namespace) -> int:
    summary = crawl_taobao_sf_locations(
        cdp_endpoint=args.cdp_endpoint,
        output_path=args.output,
        all_locations_path=args.all_locations_file,
        category=args.category,
        delay_seconds=float(args.delay_seconds),
        wait_ms=int(args.wait_ms),
        province_filters=_parse_csv(args.province),
        max_provinces=args.max_provinces,
        max_cities_per_province=args.max_cities_per_province,
        resume=not bool(args.no_resume),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    observed = read_json(args.observed, default={})
    report = compare_observed_locations(all_locations_path=args.all_locations_file, observed_payload=observed)
    if args.output:
        write_json_atomic(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_merge_overrides(args: argparse.Namespace) -> int:
    observed = read_json(args.observed, default={})
    existing = read_json(args.existing, default={}) if args.existing else {}
    payload = build_override_payload(existing_payload=existing, observed_payload=observed)
    write_json_atomic(args.output, payload)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "replace_admin_provinces": payload["replace_admin_provinces"],
                "location_count": len(payload["locations"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect and reconcile Taobao SF judicial-auction location taxonomy.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl = subparsers.add_parser("crawl", help="Low-frequency, resumable live crawl from an authenticated CDP browser.")
    crawl.add_argument("--cdp-endpoint", default=project_getenv("CROW_CDP_ENDPOINT_HOST", DEFAULT_CDP_ENDPOINT))
    crawl.add_argument("--all-locations-file", type=Path, default=Path("datas") / "all_locations.json")
    crawl.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    crawl.add_argument("--category", default=DEFAULT_CATEGORY)
    crawl.add_argument("--delay-seconds", type=float, default=8.0)
    crawl.add_argument("--wait-ms", type=int, default=1500)
    crawl.add_argument("--province", default="", help="Comma-separated province filters, e.g. 上海市,江苏省. Empty means all.")
    crawl.add_argument("--max-provinces", type=int, default=None)
    crawl.add_argument("--max-cities-per-province", type=int, default=None)
    crawl.add_argument("--no-resume", action="store_true")
    crawl.set_defaults(func=cmd_crawl)

    report = subparsers.add_parser("report", help="Compare observed Taobao locations with datas/all_locations.json.")
    report.add_argument("--all-locations-file", type=Path, default=Path("datas") / "all_locations.json")
    report.add_argument("--observed", type=Path, default=DEFAULT_OUTPUT)
    report.add_argument("--output", type=Path, default=None)
    report.set_defaults(func=cmd_report)

    merge = subparsers.add_parser("merge-overrides", help="Merge completed observed provinces into taobao_sf_location_overrides.json.")
    merge.add_argument("--observed", type=Path, default=DEFAULT_OUTPUT)
    merge.add_argument("--existing", type=Path, default=DEFAULT_OVERRIDES)
    merge.add_argument("--output", type=Path, default=DEFAULT_OVERRIDES)
    merge.set_defaults(func=cmd_merge_overrides)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


__all__ = (
    '_parse_csv',
    'cmd_crawl',
    'cmd_report',
    'cmd_merge_overrides',
    'build_parser',
    'main',
)
