"""Cookie metadata contracts shared by the runtime and diagnostic tools."""

import json
from datetime import datetime

import pytest

from src import cookie_snapshot_metadata as metadata


@pytest.mark.parametrize("expiry", [1893456000, "1893456000", 1893456000000])
def test_expiry_units_and_text_produce_same_summary(expiry):
    summary = metadata.summarize_cookie_snapshot(
        [{"name": "session", "expires": expiry}]
    )
    assert summary["persistent_count"] == 1
    assert summary["session_count"] == 0
    assert summary["earliest_expiry"] == summary["latest_expiry"]
    assert summary["earliest_expiry"] == datetime.fromtimestamp(1893456000).strftime(  # noqa: DTZ006
        "%Y-%m-%d %H:%M:%S"
    )


@pytest.mark.parametrize("expiry", [None, "", -1, 0, "invalid", {}])
def test_missing_or_invalid_expiry_remains_a_session_cookie(expiry):
    summary = metadata.summarize_cookie_snapshot([{"expires": expiry}])
    assert summary["session_count"] == 1
    assert summary["persistent_count"] == 0
    assert summary["earliest_expiry"] is None
    assert summary["latest_expiry"] is None


def test_metadata_accepts_one_shot_iterators_and_never_exposes_values():
    cookies = [
        {"name": "a", "domain": ".example.invalid", "value": "synthetic-secret-a"},
        {"name": "b", "domain": ".example.invalid", "value": "synthetic-secret-b"},
    ]
    summary = metadata.summarize_cookie_snapshot(iter(cookies))
    assert summary == metadata.summarize_cookie_snapshot(reversed(cookies))
    diff = metadata.diff_cookie_snapshots(iter(cookies), reversed(cookies))
    assert diff["shared_key_count"] == 2
    assert diff["shape_fingerprint_equal"] is True
    assert diff["value_fingerprint_equal"] is True
    serialized = json.dumps([summary, diff])
    assert "synthetic-secret" not in serialized


def test_tool_exports_use_native_metadata_owners():
    from tools import browserless_seed_probe

    for name in (
        "summarize_cookie_snapshot",
        "diff_cookie_snapshots",
        "_normalize_cookie_expiry",
        "_cookie_shape_fingerprint",
        "_cookie_value_fingerprint",
        "_cookie_key",
    ):
        assert getattr(browserless_seed_probe, name) is getattr(metadata, name)
