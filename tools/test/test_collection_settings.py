import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.collection_engine_restart import RestartError
from src.collection_settings_schema import validate
from src.collection_settings_store import SettingsStore
from tools.test.collection_settings_fixtures import config_fixture


def poll(store):
    return store.poll({"effective": config_fixture(), "api_key_configured": True})


def request(**updates):
    return {
        "request_id": "settings-request-0001",
        "expected_revision": 0,
        "config": config_fixture(),
        "api_key": None,
        **updates,
    }


def test_revision_auth_claim_idempotence_and_secret_redaction(tmp_path):
    store = SettingsStore(tmp_path)
    assert store.status()["effective"] is None
    with pytest.raises(RestartError):
        store.apply(request())
    poll(store)
    payload = request(api_key="new-synthetic-secret-only")
    first = store.apply(payload)
    assert store.apply(payload) == first
    assert "synthetic-secret" not in json.dumps(store.status())
    assert (
        b"new-synthetic-secret-only" not in (store.root / "state.sqlite3").read_bytes()
    )
    command = poll(store)["command"]
    assert command["api_key"] == payload["api_key"]
    assert poll(store)["command"] is None
    receipt = {
        "request_id": command["request_id"],
        "claim": command["claim"],
        "result": "applied",
        "effective": command["config"],
        "api_key_configured": True,
    }
    with pytest.raises(RestartError):
        store.finish({**receipt, "claim": "f" * 64})
    assert store.finish(receipt)["request"]["status"] == "succeeded"
    assert store.finish(receipt)["request"]["status"] == "succeeded"
    with pytest.raises(RestartError):
        store.apply(request(request_id="settings-request-0002"))
    with pytest.raises(RestartError):
        store.apply(request(api_key="different-synthetic-secret"))


def test_single_flight_and_no_command_replay_after_timeout(tmp_path):
    now = [0.0]
    store = SettingsStore(tmp_path, now=lambda: now[0])
    poll(store)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: store.apply(request()), range(8)))
    assert len({row["request"]["id"] for row in rows}) == 1
    command = poll(store)["command"]
    now[0] = 901
    assert store.status()["request"]["status"] == "unknown"
    assert poll(SettingsStore(tmp_path, now=lambda: now[0]))["command"] is None
    with pytest.raises(RestartError):
        store.apply(request(request_id="settings-request-0002", expected_revision=1))
    receipt = {
        "request_id": command["request_id"],
        "claim": command["claim"],
        "result": "rolled_back",
        "effective": config_fixture(),
        "api_key_configured": True,
    }
    assert store.finish(receipt)["request"]["status"] == "failed"


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.update(shell="delete everything"),
        lambda c: c["workers"].update(links=True),
        lambda c: c["workers"].update(details=9),
        lambda c: c["intervals"].update(success_delay=float("nan")),
        lambda c: c["ai"].update(base_url="https://user:password@example.invalid"),
        lambda c: c["ai"].update(model="gpt-fixture"),
    ],
)
def test_closed_schema_rejects_unsafe_or_invalid_settings(change):
    config = config_fixture()
    change(config)
    with pytest.raises(RestartError):
        validate(config)


@pytest.mark.parametrize("consumer", ["native", "facade"])
def test_routes_require_distinct_tokens_and_never_return_keys(
    tmp_path, monkeypatch, consumer
):
    from src import server, server_collection_settings

    monkeypatch.setenv("FAPAI_ENGINE_CONTROL_ROOT", str(tmp_path))
    owner = server_collection_settings if consumer == "native" else server
    for role, char in (("operator", "o"), ("agent", "a")):
        path = tmp_path / role
        path.write_text(char * 40)
        monkeypatch.setenv("FAPAI_ENGINE_" + role.upper() + "_TOKEN_FILE", str(path))
    store = SettingsStore(tmp_path)
    monkeypatch.setattr(
        server_collection_settings, "_collection_settings_store", lambda: store
    )

    class Handler:
        def __init__(self, path, token, body):
            self.path = "/api/collection/settings" + path
            raw = json.dumps(body).encode()
            self.headers = {
                "Content-Length": str(len(raw)),
                "X-FAPAI-Control-Token": token,
            }
            self.rfile = io.BytesIO(raw)
            self.result = None

        def send_json(self, result):
            self.result = result

        def send_error_json(self, **result):
            self.result = result

    handler = Handler(
        "/poll", "o" * 40, {"effective": config_fixture(), "api_key_configured": True}
    )
    owner._server_collection_settings(handler)
    assert handler.result["status"] == 403
    handler = Handler(
        "/poll", "a" * 40, {"effective": config_fixture(), "api_key_configured": True}
    )
    owner._server_collection_settings(handler)
    assert handler.result["ok"]
    handler = Handler("", "o" * 40, {})
    owner._server_collection_settings(handler, read=True)
    assert handler.result["available"]
    assert "api_key" not in handler.result["effective"]["ai"]


@pytest.mark.parametrize("claim", [True, False])
def test_secret_file_removed_after_claim_or_expiry(tmp_path, claim):
    now = [0.0]
    store = SettingsStore(tmp_path, now=lambda: now[0])
    poll(store)
    store.apply(request(api_key="synthetic-secret-for-cleanup"))
    secrets = [path for path in store.root.iterdir() if len(path.name) == 48]
    assert len(secrets) == 1
    if claim:
        assert poll(store)["command"]["api_key"] == "synthetic-secret-for-cleanup"
    else:
        now[0] = 121
        assert store.status()["request"]["status"] == "expired"
    assert not secrets[0].exists()


def test_external_drift_increments_revision_and_wrong_rollback_is_rejected(tmp_path):
    store = SettingsStore(tmp_path)
    poll(store)
    changed = config_fixture()
    changed["workers"]["details"] = 2
    store.poll({"effective": changed, "api_key_configured": True})
    assert store.status()["revision"] == 1
    with pytest.raises(RestartError):
        store.apply(request())
    store.apply(request(expected_revision=1))
    command = store.poll({"effective": changed, "api_key_configured": True})["command"]
    assert command["previous"] == changed
    receipt = {
        "request_id": command["request_id"],
        "claim": command["claim"],
        "result": "rolled_back",
        "effective": config_fixture(),
        "api_key_configured": True,
    }
    with pytest.raises(RestartError):
        store.finish(receipt)
    assert (
        store.finish({**receipt, "effective": changed})["request"]["status"] == "failed"
    )
