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
