"""Existing mailbox records keep their original request-ID binding after restart."""

import json
import sqlite3

import pytest

from src.collection_engine_restart import RestartError
from src.collection_settings_store import SettingsStore
from tools.test.collection_settings_fixtures import config_fixture

pytestmark = pytest.mark.security


def poll(store):
    return store.poll({"effective": config_fixture(), "api_key_configured": True})


def request():
    return {
        "request_id": "settings-retry-compatibility-01",
        "expected_revision": 0,
        "config": config_fixture(),
        "api_key": "synthetic-api-key-for-compatibility",
    }


@pytest.mark.parametrize(
    "status", ["applying", "succeeded", "failed", "expired", "unknown"]
)
def test_prior_request_ids_remain_bound_after_key_erasure_and_store_restart(
    tmp_path, status
):
    store = SettingsStore(tmp_path, now=lambda: 1.0)
    poll(store)
    payload = request()
    store.apply(payload)
    assert poll(store)["command"]["api_key"] == payload["api_key"]
    with sqlite3.connect(store.root / "state.sqlite3") as db:
        db.row_factory = sqlite3.Row
        db.execute("UPDATE requests SET status=?", (status,))
        before = dict(db.execute("SELECT * FROM requests").fetchone())
    assert before["key_ref"] is None
    assert [path.name for path in store.root.iterdir()] == ["state.sqlite3"]
    restarted = SettingsStore(tmp_path, now=lambda: 1.0)
    result = restarted.apply(payload)
    assert result["request"] == store.public_request(before)
    assert poll(restarted)["command"] is None
    assert restarted.status()["revision"] == 1
    with pytest.raises(RestartError, match="different settings"):
        restarted.apply({**payload, "api_key": "synthetic-different-credential"})
    changed = config_fixture()
    changed["workers"]["details"] = 2
    with pytest.raises(RestartError, match="different settings"):
        restarted.apply({**payload, "config": changed})
    status_payload = restarted.status()
    assert "fingerprint" not in status_payload["request"]
    assert payload["api_key"] not in json.dumps(status_payload)
    assert (
        payload["api_key"].encode() not in (store.root / "state.sqlite3").read_bytes()
    )
    with sqlite3.connect(store.root / "state.sqlite3") as db:
        db.row_factory = sqlite3.Row
        assert dict(db.execute("SELECT * FROM requests").fetchone()) == before
