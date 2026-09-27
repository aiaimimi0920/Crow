"""The service uses a production owner and the existing CLI remains callable."""

import json
import sys
from types import SimpleNamespace

import pytest

from src.collection import detail_archive_fetch as owner
from src.collection.detail_service import DetailCollectionService
from tools import backfill_archived_details, prepare_recent_detail_replay
from tools import fetch_missing_detail_archives as cli


@pytest.mark.parametrize(
    "module", [cli, backfill_archived_details, prepare_recent_detail_replay]
)
def test_maintenance_cli_resolves_data_and_report_roots(module, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FAPAI_DATA_ROOT", raising=False)
    monkeypatch.setattr(sys, "argv", [module.__name__])
    defaults = module.parse_args()
    assert defaults.data_root == module.REPO_ROOT / "FPFData" / "datas"
    assert defaults.output_path.parent == defaults.data_root / "maintenance"
    monkeypatch.setenv("FAPAI_DATA_ROOT", str(tmp_path / "installed-data"))
    configured = module.parse_args()
    assert configured.data_root == tmp_path / "installed-data"
    assert configured.output_path.parent == configured.data_root / "maintenance"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__name__,
            "--data-root",
            str(tmp_path / "override"),
            "--output-path",
            str(tmp_path / "preview.json"),
        ],
    )
    explicit = module.parse_args()
    assert explicit.data_root == tmp_path / "override"
    assert explicit.output_path == tmp_path / "preview.json"
    assert list(tmp_path.iterdir()) == []


def test_service_fetch_does_not_import_cli_module(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "tools.fetch_missing_detail_archives", None)
    monkeypatch.setattr(
        owner,
        "create_collection_repository_from_env",
        lambda **_: SimpleNamespace(enabled=False),
    )
    monkeypatch.setattr(owner.requests, "Session", lambda: SimpleNamespace(headers={}))
    service = DetailCollectionService(tmp_path)
    report = service.fetch_missing_archives(limit=7, timeout=9, dry_run=True)
    assert (
        report["candidate_count"]
        == report["fetched_count"]
        == report["touched_files"]
        == 0
    )
    assert report["limit"] == 7 and report["timeout"] == 9 and report["dry_run"] is True
    assert list(tmp_path.iterdir()) == []


def test_cli_preserves_native_entrypoint_and_report_contract(
    tmp_path, monkeypatch, capsys
):
    assert cli.fetch_missing_detail_archives is owner.fetch_missing_detail_archives
    report_path = tmp_path / "reports" / "fetch.json"
    calls = []

    def fetch(**options):
        calls.append(options)
        return {"candidate_count": 0, "dry_run": options["dry_run"]}

    monkeypatch.setattr(cli, "fetch_missing_detail_archives", fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_missing_detail_archives.py",
            "--data-root",
            str(tmp_path),
            "--limit",
            "7",
            "--timeout",
            "9",
            "--extract-risk",
            "--dry-run",
            "--output-path",
            str(report_path),
        ],
    )
    cli.main()
    assert calls == [
        {
            "data_root": tmp_path,
            "limit": 7,
            "timeout": 9,
            "extract_risk": True,
            "dry_run": True,
        }
    ]
    assert (
        json.loads(report_path.read_text(encoding="utf-8"))
        == json.loads(capsys.readouterr().out)
        == {
            "candidate_count": 0,
            "dry_run": True,
        }
    )
