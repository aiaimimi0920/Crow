"""UTC helpers preserve timestamp and clock contracts through both entry points."""

from datetime import datetime, timedelta, timezone

import pytest

from src import server, server_context, utc_timestamps


@pytest.fixture(params=[utc_timestamps, server], ids=["native", "facade"])
def timestamps(request):
    return request.param


@pytest.mark.parametrize(
    "value",
    [
        "2026-05-19 00:40:00",
        "2026-5-19 0:40:00",
        "2026-05-19T00:40:00Z",
        " 2026-05-19T00:40:00z ",
        "2026-05-19T02:40:00+02:00",
        "2026-05-18T17:40:00-07:00",
        datetime(2026, 5, 19, 0, 40),
    ],
)
def test_timestamp_parser_preserves_legacy_and_offset_inputs(timestamps, value):
    actual = timestamps._parse_utc_timestamp(value)
    assert actual == datetime(2026, 5, 19, 0, 40, tzinfo=timezone.utc)
    assert actual.tzinfo is timezone.utc


@pytest.mark.parametrize("value", [None, "", "  ", "invalid", "2026-02-30", 0])
def test_timestamp_parser_rejects_empty_or_invalid_values(timestamps, value):
    assert timestamps._parse_utc_timestamp(value) is None


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 5, 19, 0, 40),
        datetime(2026, 5, 19, 0, 40, tzinfo=timezone.utc),
        datetime(2026, 5, 18, 17, 40, tzinfo=timezone(timedelta(hours=-7))),
    ],
)
def test_normalization_treats_naive_values_as_utc(timestamps, value):
    actual = timestamps._as_utc_timestamp(value)
    assert actual == datetime(2026, 5, 19, 0, 40, tzinfo=timezone.utc)
    assert actual.tzinfo is timezone.utc


def test_normalization_accepts_missing_timestamp(timestamps):
    assert timestamps._as_utc_timestamp(None) is None


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("2026-05-19T02:00:00+02:00", "2026-05-19T00:01:00Z", True),
        ("2026-05-19T00:02:00Z", "2026-05-19T02:01:00+02:00", False),
        ("2026-05-18T17:00:00-07:00", "2026-05-19 00:00:00", True),
        ("2026-05-19T00:00:00Z", "2026-05-18T17:00:00-07:00", True),
        ("2026-05-19", "2026-05-19T00:00:00Z", True),
        ("2026-5-19 0:00:00", "2026-05-19 00:01:00", False),
        ("20260519T000000", "2026-05-19T00:01:00Z", False),
        (" alpha ", "beta", True),
        ("beta", "alpha", False),
        (None, "", True),
    ],
)
def test_timestamp_ordering_preserves_instant_and_legacy_text_rules(
    timestamps, left, right, expected
):
    assert timestamps._utc_timestamp_leq(left, right) is expected


def test_utc_clock_accepts_zero_argument_legacy_clock(monkeypatch, timestamps):
    class LegacyClock(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 19, 0, 15)

    monkeypatch.setattr(server.datetime, "datetime", LegacyClock)
    actual = timestamps._utc_now()
    assert actual == datetime(2026, 5, 19, 0, 15, tzinfo=timezone.utc)
    assert actual.tzinfo is timezone.utc


@pytest.mark.parametrize("naive", [False, True])
def test_utc_clock_requests_utc_and_normalizes_naive_clock_results(
    monkeypatch, timestamps, naive
):
    requested_timezones = []

    class InjectedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            requested_timezones.append(tz)
            return cls(2026, 5, 19, 0, 15, tzinfo=None if naive else tz)

    monkeypatch.setattr(server.datetime, "datetime", InjectedClock)
    actual = timestamps._utc_now()
    assert requested_timezones == [timezone.utc]
    assert actual == datetime(2026, 5, 19, 0, 15, tzinfo=timezone.utc)
    assert actual.tzinfo is timezone.utc


@pytest.mark.parametrize(
    "name",
    ["_utc_now", "_as_utc_timestamp", "_parse_utc_timestamp", "_utc_timestamp_leq"],
)
def test_legacy_entry_points_export_native_helpers(name):
    native = getattr(utc_timestamps, name)
    assert getattr(server_context, name) is native
    assert getattr(server, name) is native
