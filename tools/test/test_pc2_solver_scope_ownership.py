"""Scope cleanup must use the same node admission as solver execution."""

import pytest

from tools import pc2_solver_loop as loop
from tools import pc2_solver_scope as scope
from tools import pc2_solver_scope_policy as policy

LOCAL_CDP = "http://127.0.0.1:9223"


def request_status(node_id=None, cdp_endpoint=LOCAL_CDP, **extra):
    return {
        "challenge_id": "challenge-1",
        "last_request": {
            "node_id": node_id,
            "cdp_endpoint": cdp_endpoint,
            "target_url": "https://sf.taobao.com/list/example.htm",
        },
        **extra,
    }


@pytest.mark.parametrize(
    "endpoint", [LOCAL_CDP, "http://localhost:9223", "http://127.0.0.1:9223/"]
)
def test_explicit_foreign_node_cannot_be_overridden_by_cdp_alias(monkeypatch, endpoint):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    status = request_status("pc3", endpoint)
    assert not policy.node_owns_last_request(status, LOCAL_CDP, "pc2")
    assert (
        policy.node_solver_execution_block_reason(status, LOCAL_CDP, "pc2")
        == "request_owned_elsewhere"
    )


def test_explicit_local_node_keeps_public_to_internal_cdp_mapping():
    status = request_status(" PC2 ", "http://192.0.2.20:9224")
    assert policy.node_owns_last_request(status, LOCAL_CDP, "pc2")


@pytest.mark.parametrize("node_id", [None, "", "  "])
def test_legacy_request_without_node_keeps_endpoint_admission(node_id):
    assert policy.node_owns_last_request(request_status(node_id), LOCAL_CDP, "pc2")
    assert not policy.node_owns_last_request(
        request_status(node_id, "http://192.0.2.30:9224"), LOCAL_CDP, "pc2"
    )


@pytest.mark.parametrize(
    "status",
    [
        {},
        {"scopes": {"seed": request_status("pc3")}},
        {"scopes": {"seed": request_status(None, None)}},
        {"scopes": {"seed": {"challenge_id": "missing-request"}}},
        {"scopes": {"seed": request_status("pc2", challenge_id="")}},
    ],
)
def test_no_owned_challenge_skips_all_cdp_io(monkeypatch, status):
    def forbidden(*_args, **_kwargs):
        pytest.fail("unowned or idle status must not inspect or close local pages")

    monkeypatch.setattr(scope, "fetch_json", forbidden)
    monkeypatch.setattr(scope, "_create_scope_solver", forbidden)
    result = scope.compact_active_challenge_pages(LOCAL_CDP, status, "pc2")
    assert result["attempted"] is False
    assert result["closed"] == 0
    assert result["scopes"] == {}


@pytest.mark.parametrize(
    "foreign", [request_status("pc3"), request_status(None, "http://other.test:9224")]
)
def test_mixed_scopes_only_compact_owned_request(monkeypatch, foreign):
    calls = []
    tabs = [{"id": "existing-page"}]

    def fetch(url, *, timeout):
        calls.append(("fetch", url, timeout))
        return tabs

    class Solver:
        def _prune_duplicate_challenge_tabs(self, current):
            assert current is tabs
            calls.append(("prune",))
            return {"closed": 0}

    def create(*, cdp_endpoint, target_url):
        calls.append(("create", cdp_endpoint, target_url))
        return Solver()

    monkeypatch.setattr(scope, "fetch_json", fetch)
    monkeypatch.setattr(scope, "_create_scope_solver", create)
    result = scope.compact_active_challenge_pages(
        LOCAL_CDP,
        {"scopes": {"seed": request_status("pc2"), "detail": foreign}},
        "pc2",
    )
    assert result == {"attempted": True, "closed": 0, "scopes": {"seed": {"closed": 0}}}
    assert calls == [
        ("fetch", LOCAL_CDP + "/json/list", 5),
        ("create", LOCAL_CDP, "https://sf.taobao.com/list/example.htm"),
        ("prune",),
    ]


def test_legacy_compaction_caller_still_requires_endpoint_ownership(monkeypatch):
    monkeypatch.setattr(scope, "fetch_json", lambda *_a, **_kw: [])

    class Solver:
        def _prune_duplicate_challenge_tabs(self, _tabs):
            return {"closed": 0}

    monkeypatch.setattr(scope, "_create_scope_solver", lambda **_kw: Solver())
    result = scope.compact_active_challenge_pages(
        LOCAL_CDP, {"scopes": {"seed": request_status()}}
    )
    assert result["attempted"] is True
    assert set(result["scopes"]) == {"seed"}


def test_legacy_compaction_rejects_foreign_endpoint_before_cdp_io(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("foreign endpoint must not authorize local page cleanup")

    monkeypatch.setattr(scope, "fetch_json", forbidden)
    result = scope.compact_active_challenge_pages(
        LOCAL_CDP, {"scopes": {"seed": request_status(None, "http://other.test:9224")}}
    )
    assert result["attempted"] is False


def test_loop_passes_its_node_identity_to_cleanup(monkeypatch):
    class StopLoop(BaseException):
        pass

    status = {"scopes": {"seed": request_status("pc3")}}
    monkeypatch.setattr(loop, "hold_manual_window", lambda _poll: False)
    monkeypatch.setattr(loop, "prepare_solver_browser", lambda *_a: None)
    monkeypatch.setattr(loop, "IdlePointer", lambda *_a: None)
    monkeypatch.setattr(loop, "write_solver_heartbeat", lambda *_a: None)
    monkeypatch.setattr(
        loop,
        "process_pending_control_actions",
        lambda **_kw: {
            "last_probe_target": None,
            "last_auth_confirmed_at": 0,
            "handled": False,
        },
    )
    monkeypatch.setattr(loop, "read_solver_status", lambda _api: status)

    calls = []

    def cleanup(*args):
        calls.append(args)
        raise StopLoop

    monkeypatch.setattr(loop, "compact_active_challenge_pages", cleanup)
    with pytest.raises(StopLoop):
        loop.local_solver_loop(cdp_endpoint=LOCAL_CDP, expected_node_id="pc2")
    assert calls == [(LOCAL_CDP, status, "pc2")]
