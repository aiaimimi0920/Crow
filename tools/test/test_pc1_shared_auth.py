import json

import pytest

from src.nas_auth_recovery import NasAuthRecoveryCoordinator
from tools import pc1_desktop_auth as desktop
from tools import pc1_shared_auth as shared
from tools.manual_auth_snapshot import snapshot_path
from tools.pc1_desktop_recovery import RecoveryError

REQUEST = "a" * 32
URLS = {"seed": "https://sf.taobao.com/list/50025969.htm",
        "detail": "https://sf-item.taobao.com/sf_item/123456789.htm"}
RAW = json.dumps([{"name": "fixture", "value": "synthetic", "domain": ".taobao.com"}]).encode()


class Client:
    url = "http://fixture.invalid/api/collection/auth/recovery"

    def __init__(self, path):
        self.manager = NasAuthRecoveryCoordinator(path / "nas.json")
        self.manager.register_stage_auth_pc2()
        self.manager.sample(100, 20)
        self.calls = []

    def call(self, path="", body=None):
        self.calls.append((path, body))
        if not path:
            return {"ok": True, "auth_recovery": self.manager.snapshot()}
        if path == "/request":
            result = self.manager.request_manual(body["request_id"], scope=body["scope"],
                                                 target_url=body["target_url"], challenge_id=body["challenge_id"])
            if not result["ok"]:
                raise RecoveryError("handoff_busy")
            return result
        if path == "/claim":
            return self.manager.claim(body["role"], body["recovery_id"], body["node_id"])
        if path == "/snapshot_ready":
            return self.manager.snapshot_ready(**body)
        raise AssertionError(path)

    def finish(self, success=True):
        active = self.manager.snapshot()["active"]
        recovery_id = active["recovery_id"]
        self.manager.claim("pc2", recovery_id, "pc2")
        self.manager.pc2_restarting(recovery_id)
        receipt = {"recovery_id": recovery_id, "node_id": "pc2", "protocol_version": 2,
                   "scope": active["scope"], "target_url": active["target_url"],
                   "snapshot_sha256": active["snapshot"]["sha256"], "success": success,
                   "probe_authenticated": success}
        self.manager.accept_stage_result(receipt, validate_and_clear=lambda _: "", captured_count=100)
        if success and active["scope"] == "detail":
            self.manager.sample(101, 20)
        return active


@pytest.fixture
def setup(tmp_path, monkeypatch):
    captures = []
    monkeypatch.setattr(desktop, "find_target", lambda *args: "selected")
    def capture(**kwargs):
        captures.append(kwargs)
        kwargs["output_path"].write_bytes(RAW)
    monkeypatch.setattr(desktop.handoff, "complete_inplace_auth", capture)
    return Client(tmp_path), tmp_path / "cookies.json", captures


def complete(client, output, scope="detail"):
    peer = "seed" if scope == "detail" else "detail"
    return shared.shared_challenge(client, output=output, request_id=REQUEST,
                                   endpoint="unused", scope=scope, url=URLS[scope], target_id="selected",
                                   challenge_id=scope, peer_url=URLS[peer], peer_challenge_id=peer)


def poll(client, output):
    return shared.shared_challenge(client, output=output, request_id=REQUEST, status=True)


@pytest.mark.parametrize("scope", ["seed", "detail"])
def test_one_capture_two_identical_snapshots_and_independent_receipts(setup, scope):
    client, output, captures = setup
    assert complete(client, output, scope)["phase"] == "pending_pc2"
    first = client.manager.snapshot()["active"]
    assert first["scope"] == "seed"
    assert poll(client, output)["phase"] == "pending_pc2"
    client.finish()
    assert poll(client, output)["phase"] == "pending_pc2"
    second = client.manager.snapshot()["active"]
    assert second["scope"] == "detail"
    assert first["snapshot"]["sha256"] == second["snapshot"]["sha256"]
    for active in [first, second]:
        assert snapshot_path(output, active["recovery_id"], active["snapshot"]["sha256"]).read_bytes() == RAW
    client.finish()
    result = poll(client, output)
    assert result["phase"] == "succeeded"
    assert set(result["stage_results"]) == {"seed", "detail"}
    assert len(captures) == 1
    assert not output.exists()
    assert "synthetic" not in json.dumps(client.calls)
    assert complete(client, output)["phase"] == "succeeded"
    assert len(captures) == 1


@pytest.mark.parametrize("scope", ["seed", "detail"])
def test_abandoned_claim_is_resumed_without_handoff_busy(setup, scope):
    client, output, captures = setup
    original = client.manager.request_manual("b" * 32, scope=scope, target_url=URLS[scope], challenge_id=scope)["recovery"]
    client.manager.claim("pc1", original["recovery_id"], "pc1")
    assert complete(client, output)["phase"] == "pending_pc2"
    active = client.manager.snapshot()["active"]
    assert active["recovery_id"] == original["recovery_id"]
    assert active["status"] == "snapshot_ready"
    client.finish()
    poll(client, output)
    client.finish()
    assert poll(client, output)["phase"] == "succeeded"
    assert len(captures) == 1


def test_inflight_snapshot_is_not_overwritten_and_queue_continues(setup):
    client, output, captures = setup
    old = client.manager.request_manual("b" * 32, scope="seed", target_url=URLS["seed"], challenge_id="seed")["recovery"]
    client.manager.claim("pc1", old["recovery_id"], "pc1")
    client.manager.snapshot_ready(old["recovery_id"], sha256="0" * 64, cookie_count=1)
    assert complete(client, output)["code"] == "shared_queued"
    assert poll(client, output)["code"] == "shared_queued"
    assert client.manager.snapshot()["active"]["snapshot"]["sha256"] == "0" * 64
    client.finish()
    assert poll(client, output)["code"] == "shared_receiving"
    assert len(captures) == 1


def test_failed_seed_does_not_require_a_second_human_capture_for_detail(setup):
    client, output, captures = setup
    complete(client, output)
    client.finish(False)
    poll(client, output)
    client.finish()
    result = poll(client, output)
    assert result["phase"] == "failed" and result["code"] == "shared_partial"
    assert result["stage_results"]["seed"]["phase"] == "failed"
    assert result["stage_results"]["detail"]["phase"] == "succeeded"
    assert len(captures) == 1


def test_lost_ready_ack_retries_same_snapshot_without_capture(setup, monkeypatch):
    client, output, captures = setup
    original = client.call
    def call(path="", body=None):
        result = original(path, body)
        if path == "/snapshot_ready":
            raise RecoveryError("api_unavailable")
        return result
    monkeypatch.setattr(client, "call", call)
    assert complete(client, output)["code"] == "shared_retry"
    monkeypatch.setattr(client, "call", original)
    assert poll(client, output)["phase"] == "pending_pc2"
    assert len(captures) == 1


def test_snapshot_expiration_and_origin_guard(setup, monkeypatch):
    client, output, captures = setup
    complete(client, output)
    client.finish()
    monkeypatch.setattr(shared.time, "time", lambda: 10**12)
    result = poll(client, output)
    assert result["phase"] == "failed"
    assert result["stage_results"]["detail"]["code"] == "shared_snapshot_expired"
    client.url = "http://other.invalid"
    with pytest.raises(RecoveryError, match="api_not_configured"):
        poll(client, output)


def test_new_challenge_cannot_consume_old_claim(setup):
    client, output, _ = setup
    client.manager.request_manual("b" * 32, scope="seed", target_url=URLS["seed"], challenge_id="old")
    assert complete(client, output)["code"] == "shared_queued"
    assert client.manager.snapshot()["active"]["status"] == "requested"


def test_external_capture_uses_existing_two_stage_confirmation_without_cdp(setup):
    client, output, captures = setup
    imported = []
    def capture():
        imported.append(True)
        return RAW
    def submit():
        return shared.shared_challenge(client, output=output, request_id=REQUEST, scope="seed",
                                       url=URLS["seed"], target_id="edge:" + REQUEST,
                                       challenge_id="seed", peer_url=URLS["detail"],
                                       peer_challenge_id="detail", capture_snapshot=capture)
    assert submit()["phase"] == "pending_pc2"
    assert submit()["phase"] == "pending_pc2"
    assert imported == [True] and captures == []
    client.finish()
    assert poll(client, output)["phase"] == "pending_pc2"
    client.finish(False)
    result = poll(client, output)
    assert result["phase"] == "failed"
    assert result["stage_results"]["seed"]["phase"] == "succeeded"
    assert result["stage_results"]["detail"]["phase"] == "failed"
