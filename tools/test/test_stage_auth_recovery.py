import io
import json
from types import SimpleNamespace

import pytest

from src.collection.adapters.taobao_auth_target import auth_target
from src.nas_auth_recovery import NasAuthRecoveryCoordinator
from tools.pc1_desktop_recovery import recovery_phase
from tools.pc2_seed_auth_probe import seed_payload_authenticated

SEED = "https://sf.taobao.com/list/50025969__2.htm"
DETAIL = "https://sf-item.taobao.com/sf_item/123456789.htm"


def recovery(tmp_path, scope="seed"):
    manager = NasAuthRecoveryCoordinator(tmp_path / "state.json")
    manager.sample(10, 100, now=1)
    active = manager.request_manual(
        "a" * 32,
        scope=scope,
        challenge_id="challenge",
        target_url=SEED if scope == "seed" else DETAIL,
        now=2,
    )["recovery"]
    rid = active["recovery_id"]
    manager.claim("pc1", rid, "pc1", now=3)
    manager.snapshot_ready(rid, sha256="b" * 64, cookie_count=1, now=4)
    manager.claim("pc2", rid, "pc2", now=5)
    manager.pc2_restarting(rid, now=6)
    payload = {
        "recovery_id": rid,
        "scope": scope,
        "protocol_version": 2,
        "node_id": "pc2",
        "snapshot_sha256": "b" * 64,
        "success": True,
        "probe_authenticated": True,
        "target_url": active["target_url"],
    }
    return manager, payload


def test_seed_never_finishes_from_detail_growth_and_requires_matching_probe(tmp_path):
    manager, payload = recovery(tmp_path)
    manager.sample(30, 80, now=7)
    assert manager.snapshot(now=7)["active"]["scope"] == "seed"
    cleared = []
    accept = lambda p: manager.accept_stage_result(
        p,
        validate_and_clear=lambda active: cleared.append(active["scope"]),
        captured_count=30,
        now=8,
    )
    for bad in (
        {"scope": "detail"},
        {"snapshot_sha256": "c" * 64},
        {"probe_authenticated": False},
        {"target_url": DETAIL},
        {"protocol_version": 1},
    ):
        assert not accept({**payload, **bad})["ok"]
        assert not cleared
    assert accept(payload)["status"] == "succeeded"
    assert cleared == ["seed"]
    assert accept(payload)["idempotent"]
    assert cleared == ["seed"]
    assert not accept({**payload, "protocol_version": 1})["ok"]
    assert manager.snapshot(now=8)["last_result"]["reason"] == "seed_payload_verified"


def test_detail_needs_post_import_progress_and_other_scope_does_not_block_it(tmp_path):
    manager, payload = recovery(tmp_path, "detail")
    result = manager.accept_stage_result(
        payload, validate_and_clear=lambda _: None, captured_count=30, now=7
    )
    assert result["status"] == "verifying"
    manager.sample(30, 80, now=8)
    assert manager.snapshot(now=8)["active"]
    manager.sample(31, 79, blocked_scopes=("detail",), now=9)
    assert manager.snapshot(now=9)["active"]
    manager.sample(32, 78, blocked_scopes=("seed",), now=10)
    assert manager.snapshot(now=10)["last_result"]["scope"] == "detail"


def test_stage_identity_survives_reload_and_busy_never_aliases_other_recovery(tmp_path):
    manager, payload = recovery(tmp_path)
    loaded = NasAuthRecoveryCoordinator(manager.state_path)
    assert loaded.snapshot()["active"]["scope"] == "seed"
    assert loaded.request_manual("c" * 32, scope="detail", target_url=DETAIL, now=7)[
        "busy"
    ]
    assert not loaded.request_manual(
        "a" * 32, scope="detail", target_url=DETAIL, now=7
    )["ok"]
    assert (
        recovery_phase(loaded.snapshot(), payload["recovery_id"], scope="detail")[
            "phase"
        ]
        == "failed"
    )


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("changed", [False, True])
def test_api_result_clears_only_selected_scope_and_rejects_new_challenge(
    tmp_path, monkeypatch, scope, changed
):
    from src import server

    manager, payload = recovery(tmp_path, scope)
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", manager)
    # Use current timestamps so the real API's expiry logic sees a live request.
    with manager._locked_state():
        import time

        manager._state["active"]["updated_at_epoch"] = time.time()
        manager._persist_locked()
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server, "_solver_detail_captured_count", lambda: 30)
    current = {
        "challenge_id": "new-challenge" if changed else "challenge",
        "last_request": {"target_url": SEED if scope == "seed" else DETAIL},
    }
    monkeypatch.setattr(server, "_solver_scope_runtime_status", lambda _: current)
    cleared = []
    monkeypatch.setattr(
        server, "_clear_solver_manual_required_pause", lambda **kw: cleared.append(kw)
    )
    result = server._nas_auth_recovery_result(payload)
    if changed:
        assert result["status"] == "failed" and not cleared
        assert manager.snapshot()["last_result"]["reason"] == "challenge_changed"
    else:
        assert result["status"] == ("succeeded" if scope == "seed" else "verifying")
        assert cleared == [{"scope": scope, "preserve_running_state": True}]


def test_stage_request_requires_fresh_pc2_capability_and_scope_identity(
    tmp_path, monkeypatch
):
    from src import server

    manager = NasAuthRecoveryCoordinator(tmp_path / "state.json")
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", manager)
    monkeypatch.setattr(server, "_nas_auth_recovery_authorized", lambda _: (True, ""))
    monkeypatch.setattr(
        server,
        "_solver_scope_runtime_status",
        lambda scope: {
            "challenge_id": f"{scope}-challenge",
            "last_request": {"target_url": SEED},
        },
    )
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    pauses = []
    monkeypatch.setattr(
        server, "_set_collection_pause_state", lambda *a, **k: pauses.append((a, k))
    )

    def request(challenge="seed-challenge"):
        raw = json.dumps(
            {
                "request_id": "a" * 32,
                "scope": "seed",
                "protocol_version": 2,
                "challenge_id": challenge,
                "target_url": SEED,
            }
        ).encode()
        output = []
        handler = SimpleNamespace(
            headers={"Content-Length": str(len(raw))},
            rfile=io.BytesIO(raw),
            send_json=output.append,
            send_error_json=lambda **kw: output.append(kw),
        )
        server._server_desktop_auth_request(handler)
        return output[0]

    assert request()["status"] == 412
    assert not pauses and manager.snapshot()["active"] is None
    manager.register_stage_auth_pc2()
    assert request("detail-challenge")["status"] == 409
    assert request()["recovery"]["scope"] == "seed"
    assert pauses == [((True, "manual_required"), {"scope": "seed"})]


def test_seed_probe_accepts_valid_empty_list_not_blank_login_or_other_page():
    html = '<script id="sf-item-list-data">{"data":[]}</script>'
    assert seed_payload_authenticated(html, SEED, SEED)
    for body, url in [
        ("", SEED),
        ("请完成验证", SEED),
        (html, DETAIL),
        (html, "https://login.taobao.com/"),
        ('<script id="sf-item-list-data">{}</script>', SEED),
    ]:
        assert not seed_payload_authenticated(body, url, SEED)
    assert auth_target("seed", SEED + "?x5secdata=secret&page=2") == SEED + "?page=2"
    with pytest.raises(ValueError):
        auth_target("detail", SEED)


def test_pc1_detail_health_is_not_blocked_by_seed_challenge(monkeypatch):
    from tools import taobao_inplace_auth_handoff as handoff

    monkeypatch.setattr(
        handoff.browserless_seed_probe,
        "probe_seed_page",
        lambda *a, **k: pytest.fail("unrelated seed probe"),
    )
    response = SimpleNamespace(text="detail content" * 120, url=DETAIL, status_code=200)
    session = SimpleNamespace(get=lambda *a, **k: response)
    monkeypatch.setattr(
        handoff.browserless_seed_probe,
        "build_session_from_playwright_cookies",
        lambda _: session,
    )
    result = handoff._validate_cookie_http(
        [], DETAIL, user_agent="fixture", scope="detail"
    )
    assert result["healthy"] and result["list_healthy_samples"] == 0


@pytest.mark.parametrize("authenticated", [False, True])
def test_pc2_seed_receipt_reports_logical_failure_not_transport_success(
    tmp_path, monkeypatch, authenticated
):
    import hashlib

    from tools import pc2_auth_recovery as pc2

    manager, _payload = recovery(tmp_path)
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        '[{"name":"cookie2","value":"fixture","domain":".taobao.com"}]',
        encoding="utf-8",
    )
    digest = hashlib.sha256(cookie_file.read_bytes()).hexdigest()
    with manager._locked_state():
        manager._state["active"]["snapshot"]["sha256"] = digest
        manager._persist_locked()
    token_file = tmp_path / "token"
    token_file.write_text("fixture-recovery-token-0001", encoding="utf-8")
    monkeypatch.setattr(
        pc2,
        "import_cookie_snapshot_to_cdp",
        lambda *a, **k: {"sha256": digest, "cookie_count": 1},
    )
    monkeypatch.setattr(pc2, "probe_seed_access", lambda endpoint, url: authenticated)
    clear = []

    def poster(url, payload, **kwargs):
        if url.endswith("/heartbeat"):
            return {"ok": True}
        assert url.endswith("/result")
        return manager.accept_stage_result(
            payload,
            validate_and_clear=lambda active: clear.append(active["scope"]),
            captured_count=10,
            now=8,
        )

    marker = tmp_path / "marker"
    result = pc2.process_nas_auth_recovery_once(
        "http://fixture/api",
        "http://fixture/cdp",
        "pc2",
        cookie_file,
        marker,
        token_file,
        fetcher=lambda *a, **k: {"auth_recovery": manager.snapshot(now=7)},
        poster=poster,
    )
    assert result["action"] == (
        "recovery_confirmed" if authenticated else "recovery_failed"
    )
    assert clear == (["seed"] if authenticated else [])
    assert marker.exists() is not authenticated


@pytest.mark.parametrize(
    "capabilities, code",
    [
        ({}, "stage_api_upgrade_required"),
        (
            {"stage_auth_protocol": 2, "pc2_stage_auth_ready": False},
            "pc2_stage_upgrade_required",
        ),
    ],
)
def test_pc1_fails_closed_before_snapshot_on_older_peers(tmp_path, capabilities, code):
    from tools import pc1_desktop_auth as pc1
    from tools.pc1_desktop_recovery import RecoveryError

    calls = []

    def call(path="", body=None):
        calls.append(path)
        assert path == ""
        return {"auth_recovery": capabilities}

    with pytest.raises(RecoveryError, match=code):
        pc1.complete_challenge(
            SimpleNamespace(call=call),
            endpoint="unused",
            output_path=tmp_path / "cookies.json",
            request_id="a" * 32,
            challenge_id="",
            url=SEED,
            target_id="selected",
            scope="seed",
        )
    assert calls == [""] and not (tmp_path / "cookies.json").exists()
