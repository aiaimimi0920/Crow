"""Legacy bindings migrate only after an exact retry, with no command replay."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from src import collection_settings_store as settings
from src.collection_engine_restart import RestartError
from src.collection_settings_fingerprint import PREFIX
from tools.test.collection_settings_fixtures import config_fixture

pytestmark = pytest.mark.security


def _read(store):
    with sqlite3.connect(store.root / "state.sqlite3") as db:
        db.row_factory = sqlite3.Row
        return dict(db.execute("SELECT * FROM requests").fetchone())


def _poll(store):
    return store.poll({"effective": config_fixture(), "api_key_configured": True})


def _legacy_store(tmp_path, status="succeeded", key="synthetic-old-secret"):
    store = settings.SettingsStore(tmp_path, now=lambda: 1.0)
    _poll(store)
    payload = {
        "request_id": "legacy-settings-retry-01",
        "expected_revision": 0,
        "config": config_fixture(),
        "api_key": key,
    }
    store.apply(payload)
    if status != "requested":
        _poll(store)
    # Frozen a95734d2 store outputs for config_fixture(), not a new weak-hash
    # writer that could accidentally diverge with the production verifier.
    legacy = {
        "synthetic-old-secret": "9d3f04feb550a7c1a145717f16ef6f4b57b2b955f93038db3f02fe40155eb180",
        None: "927fa7f55077c001b0856540a4c5c371be2ed22eb729f27bfda49556c946f1e9",
    }[key]
    with sqlite3.connect(store.root / "state.sqlite3") as db:
        db.execute("UPDATE requests SET fingerprint=?,status=?", (legacy, status))
    return store, payload, _read(store)


@pytest.mark.parametrize(
    "status", ["requested", "applying", "succeeded", "failed", "expired", "unknown"]
)
def test_exact_legacy_retry_preserves_state_and_erased_key_behavior(tmp_path, status):
    store, payload, before = _legacy_store(tmp_path, status)
    original_files = {p.name for p in store.root.iterdir()}
    restarted = settings.SettingsStore(tmp_path, now=lambda: 1.0)
    result = restarted.apply(payload)
    after = _read(store)
    assert after.pop("fingerprint").startswith(PREFIX)
    before.pop("fingerprint")
    assert after == before
    assert result["request"] == store.public_request(before)
    assert restarted.apply(payload) == result
    assert {p.name for p in store.root.iterdir()} == original_files
    command = _poll(restarted)["command"]
    assert (command is not None) == (status == "requested")
    if command:
        assert command["api_key"] == payload["api_key"]
        assert _poll(restarted)["command"] is None
    assert restarted.status()["revision"] == 1
    assert payload["api_key"] not in json.dumps(restarted.status())


@pytest.mark.parametrize("changed", ["key", "config"])
def test_changed_legacy_retry_cannot_upgrade_or_rebind(tmp_path, changed):
    store, payload, before = _legacy_store(tmp_path)
    if changed == "key":
        payload["api_key"] += "different"
    else:
        payload["config"]["workers"]["details"] = 2
    with pytest.raises(RestartError, match="different settings"):
        store.apply(payload)
    assert _read(store) == before


def test_reads_do_not_migrate_old_rows_and_blank_key_remains_compatible(tmp_path):
    store, payload, before = _legacy_store(tmp_path, key=None)
    store.status()
    _poll(store)
    assert _read(store) == before
    assert store.apply({**payload, "api_key": ""})["request"] == store.public_request(
        before
    )
    assert _read(store)["fingerprint"].startswith(PREFIX)


def test_concurrent_legacy_retries_upgrade_once_without_replaying(
    tmp_path, monkeypatch
):
    store, payload, before = _legacy_store(tmp_path)
    create = settings.create_fingerprint
    created = []

    def capture(*args):
        result = create(*args)
        created.append(result)
        return result

    monkeypatch.setattr(settings, "create_fingerprint", capture)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(
            workers.map(
                lambda _: settings.SettingsStore(tmp_path).apply(payload), range(8)
            )
        )
    assert len(created) == 1
    assert _read(store)["fingerprint"] == created[0]
    assert all(result["request"] == store.public_request(before) for result in results)
    assert _poll(store)["command"] is None


@pytest.mark.parametrize("fault", ["kdf", "commit"])
def test_failed_upgrade_rolls_back_original_binding(tmp_path, monkeypatch, fault):
    store, payload, before = _legacy_store(tmp_path)
    connect = sqlite3.connect
    if fault == "kdf":

        def fail(*args):
            raise ValueError("synthetic KDF failure")

        monkeypatch.setattr(settings, "create_fingerprint", fail)
    else:

        class FailedCommit(sqlite3.Connection):
            def commit(self):
                raise sqlite3.OperationalError("synthetic commit failure")

        monkeypatch.setattr(
            settings.sqlite3,
            "connect",
            lambda *args, **kwargs: connect(*args, **kwargs, factory=FailedCommit),
        )
    with pytest.raises((ValueError, sqlite3.OperationalError)):
        store.apply(payload)
    monkeypatch.undo()
    assert _read(store) == before
    assert store.apply(payload)["request"] == store.public_request(before)


def test_unknown_version_fails_closed_without_rebinding(tmp_path):
    store, payload, _ = _legacy_store(tmp_path)
    with sqlite3.connect(store.root / "state.sqlite3") as db:
        db.execute("UPDATE requests SET fingerprint='future-format$opaque'")
    before = _read(store)
    with pytest.raises(ValueError, match="fingerprint format"):
        store.apply(payload)
    assert _read(store) == before


def test_unauthorized_http_request_never_reaches_storage_or_kdf(monkeypatch):
    from src import server_collection_settings as transport

    class Handler:
        path = "/api/collection/settings/apply"
        response = None

        def __init__(self):
            self.headers = {}

        def send_error_json(self, **response):
            self.response = response

    def denied(*args):
        raise RestartError("Restart authorization rejected", 403)

    monkeypatch.setattr(transport._settings_auth, "authorize", denied)
    monkeypatch.setattr(
        transport, "_collection_settings_store", lambda: pytest.fail("storage reached")
    )
    monkeypatch.setattr(
        transport, "_read_limited_body", lambda *a, **k: pytest.fail("body reached")
    )
    handler = Handler()
    transport._server_collection_settings(handler)
    assert handler.response["status"] == 403


def test_rejected_new_operation_does_not_pay_kdf_cost(tmp_path, monkeypatch):
    store = settings.SettingsStore(tmp_path, now=lambda: 1.0)
    payload = {
        "request_id": "settings-offline-001",
        "expected_revision": 0,
        "config": config_fixture(),
        "api_key": None,
    }
    monkeypatch.setattr(
        settings, "create_fingerprint", lambda *a: pytest.fail("KDF reached")
    )
    with pytest.raises(RestartError, match="offline"):
        store.apply(payload)
    _poll(store)
    with pytest.raises(RestartError, match="Settings changed"):
        store.apply({**payload, "expected_revision": 1})
    with pytest.raises(RestartError, match="Invalid AI key"):
        store.apply({**payload, "api_key": "x" * 2049})
