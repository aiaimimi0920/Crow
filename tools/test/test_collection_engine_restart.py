"""Offline mailbox and NAS API proof; no PC2/NAS process control."""

import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from src import collection_engine_restart as restart
from src import server


@pytest.fixture
def mailbox(tmp_path):
    clock = [1000.0]
    box = restart.RestartMailbox(tmp_path, now=lambda: clock[0])
    return box, clock


def test_restart_requires_online_controller_and_is_at_most_once(mailbox):
    box, _ = mailbox
    with pytest.raises(restart.RestartError, match="offline"):
        box.request("request-offline-0001")
    assert box.poll()["command"] is None
    accepted = box.request("request-restart-0001")
    assert accepted["created"] is True
    assert box.request("request-restart-0001")["created"] is False
    assert (
        box.request("request-restart-0002")["request"]["id"] == "request-restart-0001"
    )
    command = box.poll()["command"]
    assert box.poll()["command"] is None
    assert "claim" not in box.status()["request"]
    receipt = {key: command[key] for key in ("request_id", "claim")}
    receipt["result"] = "workers_ready"
    assert box.finish(receipt)["request"]["status"] == "succeeded"
    assert box.finish(receipt)["request"]["status"] == "succeeded"
    assert box.request("request-restart-0001")["created"] is False
    assert box.poll()["command"] is None


def test_concurrent_requests_have_only_one_active_command(mailbox):
    box, _ = mailbox
    box.poll()
    with ThreadPoolExecutor(max_workers=6) as pool:
        requests = list(
            pool.map(lambda n: box.request(f"concurrent-request-{n:04}"), range(6))
        )
    assert sum(row["created"] for row in requests) == 1
    with ThreadPoolExecutor(max_workers=6) as pool:
        claims = list(pool.map(lambda _: box.poll()["command"], range(6)))
    assert sum(row is not None for row in claims) == 1
    command = next(row for row in claims if row)
    box.finish(
        {
            "request_id": command["request_id"],
            "claim": command["claim"],
            "result": "workers_ready",
        }
    )
    for index in range(6):
        replay = box.request(f"concurrent-request-{index:04}")
        assert replay["created"] is False
        assert replay["request"]["id"] == command["request_id"]
    assert box.poll()["command"] is None


def test_expiration_and_process_restart_never_replay_claim(mailbox):
    box, clock = mailbox
    box.poll()
    box.request("request-expired-0001")
    clock[0] += 121
    assert box.status()["request"]["status"] == "expired"
    assert box.poll()["command"] is None
    box.request("request-claimed-0001")
    command = box.poll()["command"]
    restarted = restart.RestartMailbox(box.path.parent.parent, now=lambda: clock[0])
    assert restarted.poll()["command"] is None
    clock[0] += 601
    assert restarted.status()["request"]["status"] == "unknown"
    with pytest.raises(restart.RestartError, match="no longer active"):
        restarted.finish(
            {
                "request_id": command["request_id"],
                "claim": command["claim"],
                "result": "workers_ready",
            }
        )


def test_result_rejects_forged_claim_and_invalid_payload(mailbox):
    box, _ = mailbox
    box.poll()
    box.request("request-claimed-0001")
    command = box.poll()["command"]
    with pytest.raises(restart.RestartError):
        box.finish(
            {
                "request_id": command["request_id"],
                "claim": "错误",
                "result": "workers_ready",
            }
        )
    with pytest.raises(restart.RestartError):
        box.finish(
            {
                "request_id": command["request_id"],
                "claim": command["claim"],
                "result": [],
            }
        )
    assert (
        box.finish(
            {
                "request_id": command["request_id"],
                "claim": command["claim"],
                "result": "controller_interrupted",
            }
        )["request"]["status"]
        == "unknown"
    )


def test_settings_receipt_rejects_non_ascii_claim_without_type_error(
    tmp_path, monkeypatch
):
    from src.collection_settings_store import SettingsStore
    from tools.test.collection_settings_fixtures import config_fixture

    store = SettingsStore(tmp_path)
    store.poll({"effective": config_fixture(), "api_key_configured": True})
    requested = store.apply(
        {
            "request_id": "settings-utf8-0001",
            "expected_revision": 0,
            "config": config_fixture(),
            "api_key": None,
        }
    )
    command = store.poll({"effective": config_fixture(), "api_key_configured": True})
    assert command["command"] is not None
    with pytest.raises(restart.RestartError, match="Invalid settings claim"):
        store.finish(
            {
                "request_id": requested["request"]["id"],
                "claim": "☃",
                "result": "applied",
                "effective": command["command"]["config"],
                "api_key_configured": False,
            }
        )


@pytest.fixture
def authorized_api(monkeypatch, tmp_path, mailbox):
    tokens = {
        "operator": "operator-offline-fixture-token-00001",
        "agent": "agent-offline-fixture-token-0000001",
    }
    for role, value in tokens.items():
        path = tmp_path / f"{role}.token"
        path.write_text(value, encoding="utf-8")
        monkeypatch.setenv(f"FAPAI_ENGINE_{role.upper()}_TOKEN_FILE", str(path))
    box, _ = mailbox
    monkeypatch.setattr(server, "_engine_restart_mailbox", lambda: box)
    monkeypatch.setattr(server, "_collection_operator_start", lambda: {"ok": True})
    return tokens, box


def call_api(path, body, token=""):
    raw = json.dumps(body).encode()

    class Handler:
        def __init__(self):
            self.path = path
            self.headers = {
                "Content-Length": str(len(raw)),
                "X-FAPAI-Control-Token": token,
            }
            self.rfile = io.BytesIO(raw)
            self.result = None
            self.status = 200

        def send_json(self, result):
            self.result = result

        def send_error_json(self, *, status, **payload):
            self.status, self.result = status, payload

    handler = Handler()
    server._server_engine_control(handler)
    return handler


def test_api_fails_closed_and_separates_roles(authorized_api, monkeypatch):
    tokens, _ = authorized_api
    assert call_api(restart.PREFIX + "/poll", {}, tokens["operator"]).status == 403
    assert (
        call_api(
            restart.PREFIX, {"request_id": "request-api-00001"}, tokens["agent"]
        ).status
        == 403
    )
    assert call_api(restart.PREFIX, {}, "").status == 403
    monkeypatch.delenv("FAPAI_ENGINE_AGENT_TOKEN_FILE")
    assert call_api(restart.PREFIX + "/poll", {}, tokens["agent"]).status == 503
    assert server._engine_restart_status()["available"] is False


def test_api_rejects_shell_payloads_and_roundtrips_receipt(authorized_api, monkeypatch):
    tokens, box = authorized_api
    starts = []
    monkeypatch.setattr(
        server, "_collection_operator_start", lambda: starts.append(True)
    )
    assert (
        call_api(restart.PREFIX + "/poll", {}, tokens["agent"]).result["command"]
        is None
    )
    assert (
        call_api(
            restart.PREFIX,
            {"request_id": "request-api-00001", "command": "shutdown"},
            tokens["operator"],
        ).status
        == 400
    )
    request = {"request_id": "request-api-00001"}
    assert (
        call_api(restart.PREFIX, request, tokens["operator"]).result["created"] is True
    )
    assert (
        call_api(restart.PREFIX, request, tokens["operator"]).result["created"] is False
    )
    assert starts == [True]
    command = call_api(restart.PREFIX + "/poll", {}, tokens["agent"]).result["command"]
    receipt = {
        "request_id": command["request_id"],
        "claim": command["claim"],
        "result": "workers_ready",
    }
    result = call_api(restart.PREFIX + "/result", receipt, tokens["agent"])
    assert result.result["request"]["status"] == "succeeded"
    assert starts == [True]  # A later pause must not be undone by a receipt.
    assert box.status()["request"]["status"] == "succeeded"


@pytest.mark.parametrize(
    "reason,last_status,scoped,expected",
    [
        ("operator", "idle", False, (False, None)),
        ("operator", "manual_required", False, (True, "manual_required")),
        ("operator", "idle", True, (True, "captcha_solver")),
        ("manual_required", "manual_required", True, None),
    ],
)
def test_start_does_not_clear_challenges(
    monkeypatch, reason, last_status, scoped, expected
):
    calls = []
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", reason)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", last_status)
    monkeypatch.setattr(
        server, "_solver_scope_runtime_status", lambda _: {"paused": scoped}
    )
    monkeypatch.setattr(
        server,
        "_set_collection_pause_state",
        lambda paused, reason=None: calls.append((paused, reason)),
    )
    monkeypatch.setattr(server, "_collection_runtime_state_label", lambda: "待认证")
    assert server._collection_operator_start()["ok"] is True
    assert calls == ([expected] if expected else [])


def test_runtime_root_is_project_local_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(restart, "__file__", str(tmp_path / "src" / "restart.py"))
    monkeypatch.delenv("CROW_ENGINE_CONTROL_ROOT", raising=False)
    monkeypatch.delenv("FAPAI_ENGINE_CONTROL_ROOT", raising=False)
    monkeypatch.delenv("FAPAI_DATA_ROOT_HOST", raising=False)
    monkeypatch.delenv("CROW_DATA_ROOT_HOST", raising=False)
    assert restart.runtime_root() == tmp_path / "CrowData"


def test_engine_control_server_entrypoint_delegates_to_native_owner(monkeypatch):
    from src import server_engine_control

    calls = []

    def fake_native(handler, **dependencies):
        calls.append((handler, dependencies))

    monkeypatch.setattr(server_engine_control, "_server_engine_control", fake_native)
    handler = object()
    server._server_engine_control(handler)

    assert calls == [
        (
            handler,
            {
                "collection_operator_start": server._collection_operator_start,
                "mailbox_factory": server._engine_restart_mailbox,
            },
        )
    ]
