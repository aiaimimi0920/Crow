"""CLI summaries expose aggregate outcomes while preserving full report files."""

import json
from types import SimpleNamespace

import pytest

from tools import backfill_recent_coordinates, run_recent_enrich_maintenance
from tools.maintenance_diagnostics import coordinate_summary, maintenance_summary

PRIVATE = "synthetic-private-sample-token"
pytestmark = pytest.mark.security


@pytest.mark.parametrize("kind", ["coordinates", "maintenance"])
def test_cli_prints_only_summary_and_keeps_report(tmp_path, monkeypatch, capsys, kind):
    output_path = tmp_path / "reports" / "report.json"
    args = SimpleNamespace(
        data_root=tmp_path,
        window_days=7,
        dry_run=True,
        output_path=output_path,
        archive_limit=2,
        sample_limit=3,
        replay_limit=4,
        fetch_limit=5,
        fetch_timeout=1,
        reconcile_limit=6,
        extract_risk=False,
        prepare_replay=False,
        fetch_archives=False,
    )
    report = {
        "window_days": 7,
        "dry_run": True,
        "candidate_count": 8,
        "updated_count": 2,
        "updated_records": [{"item_id": PRIVATE, "latitude": 31.2, "longitude": 121.5}],
        "executed_actions": [PRIVATE, "coordinates"],
        "productive_actions": [PRIVATE],
        "before": {"samples": [{"has_keys": True, "community_stable_key": PRIVATE}]},
        "error": PRIVATE,
    }
    if kind == "coordinates":
        module, function, summarize = (
            backfill_recent_coordinates,
            "backfill_recent_coordinates",
            coordinate_summary,
        )
    else:
        module, function, summarize = (
            run_recent_enrich_maintenance,
            "run_recent_enrich_maintenance",
            maintenance_summary,
        )
    monkeypatch.setattr(module, "parse_args", lambda: args)
    monkeypatch.setattr(module, function, lambda *a, **kw: report)
    module.main()
    output = capsys.readouterr().out
    assert PRIVATE not in output
    assert json.loads(output) == summarize(report)
    assert json.loads(output_path.read_text(encoding="utf-8")) == report
    assert json.loads(output)["report_written"] is True


def test_summaries_never_echo_malformed_counts_or_values():
    report = {
        "window_days": PRIVATE,
        "dry_run": PRIVATE,
        "candidate_count": PRIVATE,
        "updated_count": {"password": PRIVATE},
        "executed_actions": PRIVATE,
        "productive_actions": {PRIVATE: True},
    }
    assert coordinate_summary(report) == {
        "report_written": True,
        "window_days": None,
        "dry_run": False,
        "candidate_count": None,
        "updated_count": None,
    }
    assert maintenance_summary(report) == {
        "report_written": True,
        "window_days": None,
        "dry_run": False,
        "executed_actions_count": None,
        "productive_actions_count": None,
    }


@pytest.mark.parametrize("value", [True, -1, 10**100, "123", [], None])
def test_summary_counts_only_accept_bounded_plain_integers(value):
    assert coordinate_summary({"updated_count": value})["updated_count"] is None
