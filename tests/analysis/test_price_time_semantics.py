from datetime import date

import pytest

from src.analysis.six_month.contracts import parse_date
from src.analysis.six_month.inputs import archive_candidate


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-01-31T17:00:00Z", date(2026, 2, 1)),
        ("2026-02-01T01:00:00+08:00", date(2026, 2, 1)),
        ("2026-02-01T00:30:00+09:00", date(2026, 1, 31)),
        ("2026-01-31 23:30:00", date(2026, 1, 31)),
        ("2026/01/31", date(2026, 1, 31)),
    ],
)
def test_beijing_calendar(value, expected):
    assert parse_date(value) == expected


def test_cost_estimate_never_replaces_hammer_price():
    raw = {
        "auction": {
            "transaction_price": 1000000,
            "actual_paid_price": 1200000,
            "status": "done",
        },
        "property": {"area_sqm": 100},
    }
    candidate = archive_candidate(raw, "synthetic_test")
    assert candidate["unit_price"] == 10000
    assert candidate["sold"] is False  # default schema status is not sale evidence
    assert candidate["available_at"] is None
    del raw["auction"]["transaction_price"]
    assert archive_candidate(raw, "synthetic_test")["unit_price"] is None
    raw["成交价格"] = 1000000
    raw["是否成交"] = True
    raw["实际支付总价"] = 9000000
    assert archive_candidate(raw, "synthetic_test")["unit_price"] == 10000


@pytest.mark.parametrize("status", ["\u6210\u4ea4", "ended"])
def test_archive_sold_flag_is_only_a_result_proxy(tmp_path, status):
    import json

    from src.analysis.six_month.aggregate import aggregate_archives
    from src.analysis.six_month.current_input import current_snapshot_report
    from src.analysis.six_month.inputs import audit_archives

    raw = {
        "id": 1,
        "\u662f\u5426\u6210\u4ea4": True,
        "\u57ce\u5e02": "\u5317\u4eac",
        "\u533a": "Synthetic district",
        "\u6240\u5c5e\u5c0f\u533a": "Synthetic community",
        "\u4ea4\u6613\u65f6\u95f4": "2024-01-15",
        "auction": {
            "status": status,
            "transaction_price": 1000000,
            "actual_paid_price": 1200000,
        },
        "property": {"area_sqm": 100},
    }
    path = tmp_path / "synthetic.json"
    path.write_text(json.dumps([raw]), encoding="utf-8")

    candidate = archive_candidate(raw, "synthetic_fixture")
    aggregated = aggregate_archives(tmp_path)
    evidence = "legacy_archive_sold_flag_proxy_winning_bid_and_later_completion_unverified"
    assert candidate["sold"] is True  # Compatibility: an ended row may already be flagged.
    assert candidate["raw_auction_status"] == status
    assert candidate["available_at"] is None
    assert aggregated["community_months"][0]["n"] == 1
    assert aggregated["community_months"][0]["auction_median_yuan_sqm"] == 10000
    reports = (
        candidate,
        aggregated,
        audit_archives(tmp_path),
        current_snapshot_report(tmp_path),
    )
    for output in reports:
        assert output["auction_result_evidence"] == evidence
