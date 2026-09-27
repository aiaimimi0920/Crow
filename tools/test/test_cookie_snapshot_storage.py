"""Native persistence failures must leave the last usable snapshot intact."""

import json
import os

import pytest

from src.cookie_snapshot_storage import load_cookie_snapshot, write_cookie_snapshot


@pytest.mark.parametrize("failure", ["serialize", "flush"])
def test_failed_snapshot_staging_preserves_previous_snapshot(
    tmp_path, monkeypatch, failure
):
    target = tmp_path / "cookies.json"
    original = b'[{"name":"old","value":"synthetic"}]'
    target.write_bytes(original)

    def fail_flush(_descriptor):
        raise OSError("synthetic fsync failure")

    if failure == "flush":
        monkeypatch.setattr(os, "fsync", fail_flush)
        cookies = [{"name": "new"}]
        expected_error = OSError
    else:
        cookies = [{"name": object()}]
        expected_error = TypeError

    with pytest.raises(expected_error):
        write_cookie_snapshot(cookies, target)
    assert target.read_bytes() == original
    assert list(tmp_path.iterdir()) == [target]
    assert load_cookie_snapshot(target) == json.loads(original)


def test_tool_and_runtime_share_native_snapshot_storage():
    from tools import browserless_seed_probe

    assert browserless_seed_probe.write_cookie_snapshot is write_cookie_snapshot
    assert browserless_seed_probe.load_cookie_snapshot is load_cookie_snapshot


def test_snapshot_loader_rejects_non_list_payload(tmp_path):
    target = tmp_path / "cookies.json"
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Cookie snapshot must be a JSON list"):
        load_cookie_snapshot(target)
