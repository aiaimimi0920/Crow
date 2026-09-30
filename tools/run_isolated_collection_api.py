from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TypedDict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from src.project_data_paths import resolve_project_data_root


class RuntimeConfig(TypedDict):
    repo_root: Path
    data_dir: Path
    port: int
    tls_cert_file: str | None
    tls_key_file: str | None
    collection_api_lightweight_status: bool
    db_url: str | None
    seed_location_codes: list[str]


def build_runtime_config(
    repo_root: Path,
    *,
    port: int,
    db_url: str | None = None,
    seed_location_codes: list[str] | None = None,
    tls_cert_file: str | None = None,
    tls_key_file: str | None = None,
    data_root: str | Path | None = None,
) -> RuntimeConfig:
    return {
        "repo_root": repo_root,
        "data_dir": Path(data_root)
        if data_root
        else resolve_project_data_root(repo_root) / "datas",
        "port": port,
        "tls_cert_file": tls_cert_file,
        "tls_key_file": tls_key_file,
        "collection_api_lightweight_status": True,
        "db_url": db_url,
        "seed_location_codes": list(seed_location_codes or ["110101"]),
    }


def run_server(config: RuntimeConfig) -> int:
    from src.collection_http_server import tls_context

    listener_tls = tls_context(config.get("tls_cert_file"), config.get("tls_key_file"))
    if config.get("db_url"):
        os.environ["FAPAI_DB_URL"] = str(config["db_url"])
        os.environ["FAPAI_DB_ENABLED"] = "1"
    if config.get("collection_api_lightweight_status", True):
        os.environ["FAPAI_COLLECTION_API_LIGHTWEIGHT_STATUS"] = "1"
    from src.collection.search_bootstrap import DEFAULT_CATEGORIES
    from src.collection_application import create_application
    from src.collection_server import serve_application

    app = create_application(data_root=config["data_dir"])
    try:
        repository = app.host.DB_REPOSITORY
        if (
            repository.enabled
            and config["seed_location_codes"]
            and app.host.COLLECTION_ADAPTER.bootstraps_legacy_search_tasks
        ):
            repository.ensure_seed_search_tasks(
                config["seed_location_codes"], DEFAULT_CATEGORIES, sort_param="2"
            )
        return serve_application(app, ("", config["port"]), tls=listener_tls)
    finally:
        app.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Start an isolated collection API without browser watchdog side effects."
    )
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--data-root", default=os.getenv("FAPAI_DATA_ROOT"))
    parser.add_argument("--tls-cert-file", default=None)
    parser.add_argument("--tls-key-file", default=None)
    parser.add_argument(
        "--seed-location-code", action="append", dest="seed_location_codes"
    )
    parser.add_argument("--print-config", action="store_true")
    args = parser.parse_args(argv)

    config = build_runtime_config(
        REPO_ROOT,
        port=args.port,
        db_url=args.db_url,
        tls_cert_file=args.tls_cert_file,
        tls_key_file=args.tls_key_file,
        data_root=args.data_root,
        seed_location_codes=args.seed_location_codes,
    )
    if args.print_config:
        printable = dict(config)
        printable["repo_root"] = str(printable["repo_root"])
        printable["data_dir"] = str(printable["data_dir"])
        print(json.dumps(printable, ensure_ascii=False))
        return 0
    return run_server(config)


if __name__ == "__main__":
    raise SystemExit(main())
