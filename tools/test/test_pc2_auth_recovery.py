from __future__ import annotations

import base64
import hashlib
import json

import pytest

from tools import (
    pc2_auth_recovery,
    pc2_solver_loop,
    pc2_solver_loop_control,
    pc2_solver_loop_probe,
)


def _snapshot(tmp_path):
    path = tmp_path / "taobao-cookies.json"
    cookies = [
        {
            "name": "session-cookie",
            "value": "secret-cookie-value",
            "domain": ".taobao.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "None",
        },
        {
            "name": "ignored-cookie",
            "value": "ignored-value",
            "domain": ".example.com",
            "path": "/",
        },
    ]
    path.write_text(json.dumps(cookies), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, digest


@pytest.mark.parametrize(
    ("raw_token", "expected"),
    [
        ("a" * 16, "a" * 16),
        ("a" * 4096, "a" * 4096),
        ("\n" + "a" * 16 + "\n", "a" * 16),
    ],
)
def test_load_recovery_token_accepts_ascii_boundaries_and_strips_outer_newlines(
    tmp_path, raw_token, expected
) -> None:
    path = tmp_path / "nas-auth-recovery.token"
    path.write_text(raw_token, encoding="utf-8")

    assert pc2_auth_recovery.load_recovery_token(path) == expected


@pytest.mark.parametrize(
    "raw_token",
    [
        "a" * 15,
        "a" * 4097,
        "a" * 8 + " " + "a" * 8,
        "a" * 8 + "\n" + "a" * 8,
        "a" * 15 + "雪",
    ],
)
def test_load_recovery_token_rejects_invalid_format(tmp_path, raw_token) -> None:
    path = tmp_path / "nas-auth-recovery.token"
    path.write_text(raw_token, encoding="utf-8")

    with pytest.raises(ValueError, match="token is invalid"):
        pc2_auth_recovery.load_recovery_token(path)


def test_load_cookie_snapshot_verifies_digest_and_filters_non_taobao_domains(tmp_path):
    path, digest = _snapshot(tmp_path)

    cookies, metadata = pc2_auth_recovery.load_cookie_snapshot(
        path, expected_sha256=digest
    )

    assert len(cookies) == 1
    assert cookies[0]["name"] == "session-cookie"
    assert metadata == {"sha256": digest, "cookie_count": 1}


def test_ensure_cookie_snapshot_downloads_missing_snapshot_from_nas_atomically(
    tmp_path,
):
    source, digest = _snapshot(tmp_path)
    raw = source.read_bytes()
    source.unlink()
    requested = []

    def fetcher(url, *, timeout, headers):
        requested.append((url, timeout, headers))
        return {
            "ok": True,
            "recovery_id": "auth-recovery-1",
            "sha256": digest,
            "encoding": "base64",
            "snapshot": base64.b64encode(raw).decode("ascii"),
        }

    result = pc2_auth_recovery.ensure_cookie_snapshot(
        "http://nas:8001/api",
        "auth-recovery-1",
        source,
        expected_sha256=digest,
        headers={"X-Fapai-Recovery-Token": "test-token"},
        fetcher=fetcher,
    )

    assert source.read_bytes() == raw
    assert result == {"sha256": digest, "cookie_count": 1, "source": "nas"}
    assert requested == [
        (
            "http://nas:8001/api/collection/auth/recovery/snapshot?recovery_id=auth-recovery-1",
            20,
            {"X-Fapai-Recovery-Token": "test-token"},
        )
    ]


def test_import_cookie_snapshot_uses_browser_storage_and_verifies_identities(
    tmp_path, monkeypatch
):
    path, digest = _snapshot(tmp_path)
    sent = []

    class FakeWebSocket:
        def settimeout(self, _timeout):
            pass

        def send(self, message):
            sent.append(json.loads(message))

        def recv(self):
            request = sent[-1]
            if request["method"] == "Storage.getCookies":
                return json.dumps(
                    {
                        "id": request["id"],
                        "result": {
                            "cookies": [
                                {
                                    "name": "session-cookie",
                                    "domain": ".taobao.com",
                                    "path": "/",
                                }
                            ]
                        },
                    }
                )
            return json.dumps({"id": request["id"], "result": {}})

        def close(self):
            pass

    monkeypatch.setattr(
        pc2_auth_recovery,
        "fetch_json",
        lambda *_args, **_kwargs: {
            "webSocketDebuggerUrl": "ws://browser/devtools/browser/1"
        },
    )
    import websocket

    monkeypatch.setattr(
        websocket, "create_connection", lambda *_args, **_kwargs: FakeWebSocket()
    )

    result = pc2_auth_recovery.import_cookie_snapshot_to_cdp(
        path,
        "http://browser:9224",
        expected_sha256=digest,
    )

    assert [request["method"] for request in sent] == [
        "Storage.setCookies",
        "Storage.getCookies",
    ]
    assert result["imported_count"] == 1
    assert result["verified_count"] == 1


def test_import_cookie_snapshot_requires_session_identities_not_rotating_analytics(
    tmp_path, monkeypatch
):
    path = tmp_path / "taobao-cookies.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "cookie2",
                    "value": "auth",
                    "domain": ".taobao.com",
                    "path": "/",
                },
                {
                    "name": "analytics",
                    "value": "rotates",
                    "domain": ".taobao.com",
                    "path": "/",
                },
            ]
        ),
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sent = []

    class FakeWebSocket:
        def settimeout(self, _timeout):
            pass

        def send(self, message):
            sent.append(json.loads(message))

        def recv(self):
            request = sent[-1]
            cookies = (
                [{"name": "cookie2", "domain": ".taobao.com", "path": "/"}]
                if request["method"] == "Storage.getCookies"
                else []
            )
            return json.dumps({"id": request["id"], "result": {"cookies": cookies}})

        def close(self):
            pass

    monkeypatch.setattr(
        pc2_auth_recovery,
        "fetch_json",
        lambda *_args, **_kwargs: {
            "webSocketDebuggerUrl": "ws://browser/devtools/browser/1"
        },
    )
    import websocket

    monkeypatch.setattr(
        websocket, "create_connection", lambda *_args, **_kwargs: FakeWebSocket()
    )

    result = pc2_auth_recovery.import_cookie_snapshot_to_cdp(
        path, "http://browser:9224", expected_sha256=digest
    )

    assert result["verified_count"] == 1
    assert result["session_cookie_count"] == 1
    assert result["verified_session_cookie_count"] == 1


@pytest.mark.parametrize("initial_status", ["snapshot_ready", "restarting"])
def test_recovery_cycle_imports_without_restart_and_waits_for_progress(
    tmp_path, monkeypatch, initial_status
):
    path, digest = _snapshot(tmp_path)
    marker = tmp_path / "pc2-auth-recovery-marker.json"
    token_path = tmp_path / "nas-auth-recovery.token"
    token_path.write_text("test-recovery-token\n", encoding="utf-8")
    active = {
        "recovery_id": "auth-recovery-1",
        "status": initial_status,
        "snapshot": {"sha256": digest, "cookie_count": 1},
    }
    posted = []

    def fetcher(_url, *, timeout, headers):
        assert timeout == 10
        assert headers == {"X-Fapai-Recovery-Token": "test-recovery-token"}
        return {"auth_recovery": {"active": dict(active)}}

    def poster(url, payload, *, timeout, headers):
        assert headers == {"X-Fapai-Recovery-Token": "test-recovery-token"}
        posted.append((url, dict(payload), timeout))
        if url.endswith("/claim"):
            active["status"] = "pc2_claimed"
        elif url.endswith("/pc2_restarting"):
            active["status"] = "restarting"
        elif url.endswith("/result"):
            active["status"] = "verifying"
            return {"ok": True, "status": "verifying"}
        return {"ok": True}

    imports = []
    monkeypatch.setattr(
        pc2_auth_recovery,
        "import_cookie_snapshot_to_cdp",
        lambda *_args, **kwargs: (
            imports.append(kwargs["expected_sha256"])
            or {
                "sha256": digest,
                "cookie_count": 1,
                "imported_count": 1,
                "verified_count": 1,
            }
        ),
    )

    first = pc2_auth_recovery.process_nas_auth_recovery_once(
        "http://nas:8001/api",
        "http://browser:9223",
        "pc2",
        path,
        marker,
        token_path,
        fetcher=fetcher,
        poster=poster,
    )
    assert first["action"] == "recovery_verifying"
    assert not marker.exists()

    second = pc2_auth_recovery.process_nas_auth_recovery_once(
        "http://nas:8001/api",
        "http://browser:9223",
        "pc2",
        path,
        marker,
        token_path,
        fetcher=fetcher,
        poster=poster,
    )
    assert second["action"] == "waiting_for_collection_progress"
    assert marker.exists() is False
    assert imports == [digest]
    assert all(
        "secret-cookie-value" not in json.dumps(payload) for _, payload, _ in posted
    )
    expected = ["heartbeat"]
    if initial_status == "snapshot_ready":
        expected += ["claim", "pc2_restarting"]
    assert [url.rsplit("/", 1)[-1] for url, _, _ in posted] == [
        *expected,
        "result",
        "heartbeat",
    ]
    result_payload = next(
        payload for url, payload, _ in posted if url.endswith("/result")
    )
    assert result_payload["reason"] == "cookie_import_verified"


def test_local_solver_exits_pid1_after_recovery_requests_restart(monkeypatch):
    heartbeats = []
    monkeypatch.setattr(
        pc2_solver_loop_probe, "check_cdp_healthy", lambda _endpoint: True
    )
    monkeypatch.setattr(
        pc2_solver_loop_control, "nas_auth_recovery_client_enabled", lambda: True
    )
    monkeypatch.setattr(
        pc2_solver_loop_control,
        "process_nas_auth_recovery_once",
        lambda *_args, **_kwargs: {
            "action": "restart_requested",
            "recovery_id": "auth-recovery-1",
            "cookie_count": 1,
        },
    )
    for module in (pc2_solver_loop, pc2_solver_loop_control, pc2_solver_loop_probe):
        monkeypatch.setattr(
            module,
            "write_solver_heartbeat",
            lambda phase, **details: heartbeats.append((phase, details)),
        )

    with pytest.raises(SystemExit) as exc_info:
        pc2_solver_loop.local_solver_loop(
            api_base_url="http://nas:8001/api",
            cdp_endpoint="http://browser:9223",
            poll_seconds=1,
            expected_node_id="pc2",
        )

    assert exc_info.value.code == 75
    assert heartbeats[-1] == (
        "auth_recovery_restart",
        {"recovery_id": "auth-recovery-1"},
    )
