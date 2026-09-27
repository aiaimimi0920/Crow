"""Native cookie owners retain live facade dependencies and safety boundaries."""

from src.auth_cookie_paths import AuthCookiePaths
from src.runtime_state import RuntimeState
from src.server_auth_cookie import AuthCookieSnapshot
from src.solver_captcha_reports import SolverCaptchaReports


def test_cookie_exports_are_native_and_share_context_identity():
    from src import server

    assert not hasattr(server, "_CORE_MODULES")
    for owner_type in (AuthCookiePaths, AuthCookieSnapshot, SolverCaptchaReports):
        for name in owner_type.__all__:
            method = getattr(server, name)
            assert isinstance(method.__self__, owner_type)
            assert getattr(server._CONTEXT, name) is method


def test_saved_cookie_paths_and_state_observe_replacements(tmp_path, monkeypatch):
    from src import server

    resolve = server._resolve_auth_cookie_snapshot_path
    update = server._set_auth_cookie_snapshot_state
    status = server._auth_cookie_snapshot_runtime_status
    monkeypatch.delenv("FAPAI_COOKIE_SNAPSHOT", raising=False)
    monkeypatch.setattr(
        server, "_auth_cookie_snapshot_root_candidates", lambda: [tmp_path]
    )
    assert resolve({"node_id": "node-new"}) == str(
        tmp_path / "secrets" / "nodes" / "node-new" / "taobao-cookies.json"
    )
    first = RuntimeState()
    second = RuntimeState()
    monkeypatch.setattr(server, "RUNTIME", first)
    update(status="first")
    monkeypatch.setattr(server, "RUNTIME", second)
    update(status="second")
    assert status()["status"] == "second"
    assert first.cookie_snapshot.snapshot()["status"] == "first"


def test_saved_refresh_respects_replaced_endpoint_permission(monkeypatch):
    from src import server

    refresh = server._refresh_auth_cookie_snapshot
    monkeypatch.setattr(
        server, "_resolve_auth_cookie_snapshot_path", lambda _: "unused.json"
    )
    monkeypatch.setattr(
        server, "_normalize_solver_cdp_endpoint", lambda _: "http://example.invalid"
    )
    monkeypatch.setattr(server, "_cdp_endpoint_permitted", lambda _: False)
    exports = []
    monkeypatch.setattr(
        server, "_export_auth_cdp_cookies", lambda endpoint: exports.append(endpoint)
    )
    assert refresh({}) == {"refreshed": False, "reason": "cdp_endpoint_not_permitted"}
    assert exports == []


def test_blocked_report_keeps_epoch_and_attempts_and_surfaces_persistence_failure(
    monkeypatch,
):
    from src import server

    report = server._node_solver_blocked_report_payload
    events = []
    persisted = []
    monkeypatch.setattr(server, "_build_solver_request", lambda _: {"scope": "seed"})
    monkeypatch.setattr(server, "_refresh_solver_last_request", lambda _: None)
    monkeypatch.setattr(server, "_challenge_scope_for_request", lambda _: "seed")
    monkeypatch.setattr(
        server, "_begin_solver_challenge", lambda _: events.append("begin")
    )
    monkeypatch.setattr(
        server,
        "_read_solver_scope_state",
        lambda _: {
            "node_solver_blocked_at_epoch": 20,
            "node_solver_blocked_attempts": 10,
        },
    )
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", dict)

    def persist(scope, state):
        events.append("persist")
        persisted.append((scope, state.copy()))
        return "synthetic persistence failure"

    monkeypatch.setattr(server, "_persist_solver_scope_state", persist)
    monkeypatch.setattr(
        server,
        "_set_collection_pause_state",
        lambda paused, reason, **kwargs: events.append(
            (paused, reason, kwargs["scope"])
        ),
    )
    result = report({"node_solver_blocked_attempts": 3})
    assert result["state_error"] == "synthetic persistence failure"
    assert result["scope"] == "seed"
    assert events == ["begin", "persist", (True, "manual_required", "seed")]
    assert persisted[0][0] == "seed"
    assert persisted[0][1]["node_solver_blocked_at_epoch"] == 20
    assert persisted[0][1]["node_solver_blocked_attempts"] == 10
    assert persisted[0][1]["manual_only"] is True
