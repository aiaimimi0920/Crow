"""A detail proof must neither depend on nor advertise seed health."""

from copy import deepcopy

import pytest

from src.runtime_state import RuntimeState

TARGET = "https://sf-item.taobao.com/sf_item/864933660682.htm"
ENDPOINT = "http://192.168.15.20:9224"


@pytest.fixture
def snapshot_host(monkeypatch, tmp_path):
    from src import server

    state = {
        "challenge_id": "detail-current",
        "last_request": {
            "scope": "detail",
            "node_id": "pc2",
            "target_url": TARGET,
            "cdp_endpoint": ENDPOINT,
        },
    }
    writes, probes, exports = [], [], []
    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setattr(server, "_read_solver_scope_state", lambda _: deepcopy(state))
    monkeypatch.setattr(
        server,
        "_resolve_auth_cookie_snapshot_path",
        lambda _: str(tmp_path / "cookies.json"),
    )
    monkeypatch.setattr(
        server,
        "_normalize_solver_cdp_endpoint",
        lambda value: str(value or "").rstrip("/"),
    )
    monkeypatch.setattr(server, "_cdp_endpoint_permitted", lambda _: True)

    def export(endpoint, **_options):
        exports.append(endpoint)
        return [
            {
                "name": "cookie2",
                "value": "synthetic",
                "domain": ".taobao.com",
                "path": "/",
            }
        ]

    def health(_cookies, sample_urls, **kwargs):
        probes.append((sample_urls, kwargs))
        return {
            "healthy": False,
            "scope": "detail",
            "scope_healthy": kwargs.get("detail_target_url") == TARGET,
            "scope_target_url": TARGET,
        }

    monkeypatch.setattr(server, "_export_auth_cdp_cookies", export)
    monkeypatch.setattr(
        server, "_summarize_auth_cookies", lambda cookies: {"count": len(cookies)}
    )
    monkeypatch.setattr(server, "_probe_auth_cookie_snapshot_health", health)
    monkeypatch.setattr(
        server, "_write_auth_cookie_snapshot", lambda *args: writes.append(args)
    )
    payload = {
        "scope": "detail",
        "challenge_id": "detail-current",
        "node_id": "pc2",
        "cdp_endpoint": ENDPOINT,
    }
    return server, state, writes, probes, exports, payload


def test_detail_snapshot_uses_bound_detail_not_seed_health(snapshot_host):
    server, _, writes, probes, exports, payload = snapshot_host
    # Caller-provided samples and a different target cannot retarget the proof.
    payload.update(
        sample_urls=["https://sf.taobao.com/list/other.htm"],
        target_url="https://sf-item.taobao.com/sf_item/999.htm",
    )
    result = server._refresh_auth_cookie_snapshot(payload)
    assert result["refreshed"] is True
    assert result["health"]["healthy"] is False
    assert result["health"]["scope_healthy"] is True
    assert probes == [
        ([TARGET], {"cdp_endpoint": ENDPOINT, "detail_target_url": TARGET})
    ]
    assert exports == [ENDPOINT] and len(writes) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"challenge_id": "older"},
        {"challenge_id": None},
        {"node_id": "pc1"},
        {"cdp_endpoint": "http://192.168.15.130:9224"},
    ],
)
def test_detail_snapshot_rejects_wrong_generation_or_owner(snapshot_host, change):
    server, _, writes, probes, exports, payload = snapshot_host
    payload.update(change)
    result = server._refresh_auth_cookie_snapshot(payload)
    assert result["refreshed"] is False
    assert result["reason"] == "cookie_snapshot_scope_mismatch"
    assert not writes and not probes and not exports


@pytest.mark.parametrize(
    "target",
    [
        "https://example.invalid/",
        "https://sf.taobao.com/list/200782003__2.htm",
        "http://sf-item.taobao.com/sf_item/864933660682.htm",
    ],
)
def test_detail_snapshot_rejects_invalid_bound_target(snapshot_host, target):
    server, state, writes, probes, exports, payload = snapshot_host
    state["last_request"]["target_url"] = target
    result = server._refresh_auth_cookie_snapshot(payload)
    assert result["refreshed"] is False
    assert not writes and not probes and not exports


def test_detail_snapshot_rechecks_generation_before_cookie_write(
    snapshot_host, monkeypatch
):
    server, state, writes, _, _, payload = snapshot_host

    def health(*_args, **_kwargs):
        state["challenge_id"] = "new-generation"
        return {
            "healthy": False,
            "scope": "detail",
            "scope_healthy": True,
            "scope_target_url": TARGET,
        }

    monkeypatch.setattr(server, "_probe_auth_cookie_snapshot_health", health)
    result = server._refresh_auth_cookie_snapshot(payload)
    assert result["refreshed"] is False
    assert result["reason"] == "cookie_snapshot_scope_mismatch"
    assert not writes


def test_seed_does_not_accept_a_detail_only_health_proof(snapshot_host):
    server, _, writes, probes, _, payload = snapshot_host
    payload["scope"] = "seed"
    result = server._refresh_auth_cookie_snapshot(payload)
    assert result["refreshed"] is False
    assert result["reason"] == "cookie_snapshot_candidate_unhealthy"
    assert "detail_target_url" not in probes[0][1]
    assert not writes


@pytest.mark.parametrize("key", ["node_id", "cdp_endpoint"])
def test_missing_durable_detail_owner_fails_closed(snapshot_host, key):
    server, state, writes, probes, exports, payload = snapshot_host
    state["last_request"].pop(key)
    result = server._refresh_auth_cookie_snapshot(payload)
    assert result["reason"] == "cookie_snapshot_scope_mismatch"
    assert not writes and not probes and not exports


def test_implicit_cdp_owner_is_rechecked_after_probe(snapshot_host, monkeypatch):
    server, state, writes, _, _, payload = snapshot_host
    payload.pop("cdp_endpoint")

    def health(*_args, **_kwargs):
        state["last_request"]["cdp_endpoint"] = "http://192.168.15.130:9224"
        return {"scope": "detail", "scope_healthy": True, "scope_target_url": TARGET}

    monkeypatch.setattr(server, "_probe_auth_cookie_snapshot_health", health)
    assert (
        server._refresh_auth_cookie_snapshot(payload)["reason"]
        == "cookie_snapshot_scope_mismatch"
    )
    assert not writes


@pytest.mark.parametrize(
    "change",
    [{"scope": "seed"}, {"scope_target_url": TARGET.replace("864933660682", "999")}],
)
def test_health_cannot_replace_scope_or_target_binding(
    snapshot_host, monkeypatch, change
):
    server, _, writes, _, _, payload = snapshot_host
    health = {
        "healthy": True,
        "scope": "detail",
        "scope_healthy": True,
        "scope_target_url": TARGET,
        **change,
    }
    monkeypatch.setattr(
        server, "_probe_auth_cookie_snapshot_health", lambda *_args, **_kwargs: health
    )
    assert (
        server._refresh_auth_cookie_snapshot(payload)["reason"]
        == "cookie_snapshot_candidate_unhealthy"
    )
    assert not writes


def test_detail_export_receives_durable_target_not_caller_target(
    snapshot_host, monkeypatch
):
    server, _, writes, _, _, payload = snapshot_host
    calls = []

    def export(endpoint, **options):
        calls.append((endpoint, options))
        return []

    monkeypatch.setattr(server, "_export_auth_cdp_cookies", export)
    payload["target_url"] = "https://sf-item.taobao.com/sf_item/999.htm"
    assert server._refresh_auth_cookie_snapshot(payload)["refreshed"] is True
    assert calls == [(ENDPOINT, {"detail_target_url": TARGET})]
    assert len(writes) == 1
