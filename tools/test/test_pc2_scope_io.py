"""Native notification and CDP failure boundaries, without network or browser I/O."""

import pytest

from tools import pc2_solver_scope as scope


def test_scope_io_facade_exports_original_functions():
    from tools import pc2_local_solver

    for name in (
        "notify_force_reset",
        "notify_manual_challenge",
        "notify_solver_blocked",
        "check_cdp_healthy",
        "close_challenge_pages_for_scope",
        "compact_active_challenge_pages",
    ):
        original = getattr(scope, name)
        assert getattr(pc2_local_solver, name) is original
        assert original.__globals__ is vars(scope)


def test_force_reset_preserves_scope_identity_and_non_dict_response(monkeypatch):
    requests = []

    def post(url, payload, *, timeout):
        requests.append((url, payload, timeout))
        return "not-json-object"

    monkeypatch.setattr(scope, "post_json", post)
    assert scope.notify_force_reset("https://api.test/api/", "seed", "seed-1") == {
        "ok": False,
        "payload": "not-json-object",
    }
    assert requests == [
        (
            "https://api.test/api/collection/auth/force_reset",
            {"source": "pc2_local_solver", "scope": "seed", "challenge_id": "seed-1"},
            10,
        )
    ]


def test_cdp_health_probes_version_after_list_failure(monkeypatch):
    calls = []

    def fetch(url, *, timeout):
        calls.append((url, timeout))
        if url.endswith("/list"):
            raise OSError("list unavailable")
        return {}

    monkeypatch.setattr(scope, "fetch_json", fetch)
    assert scope.check_cdp_healthy("http://cdp.test/")
    assert calls == [
        ("http://cdp.test/json/list", 5),
        ("http://cdp.test/json/version", 5),
    ]


def test_cleanup_keeps_processing_after_one_target_fails(monkeypatch):
    closed = []
    tabs = [
        {"id": target, "type": "page", "url": "https://sf.taobao.com/list/example.htm"}
        for target in ("broken", "good")
    ]

    class Solver:
        def _close_cdp_target(self, target):
            if target == "broken":
                raise RuntimeError("target already gone")
            closed.append(target)
            return True

    monkeypatch.setattr(scope, "fetch_json", lambda *_a, **_kw: tabs)
    monkeypatch.setattr(scope, "_create_scope_solver", lambda **_kw: Solver())
    result = scope.close_challenge_pages_for_scope("http://cdp.test", "seed")
    assert result["target_ids"] == closed == ["good"]
    assert result["closed"] == 1


def test_compaction_reuses_snapshot_when_refresh_fails(monkeypatch):
    tabs = [{"id": "original"}]
    fetch_calls = []
    snapshots = []
    targets = []

    def fetch(*_args, **_kwargs):
        fetch_calls.append(True)
        if len(fetch_calls) > 1:
            raise OSError("refresh unavailable")
        return tabs

    class Solver:
        def _prune_duplicate_challenge_tabs(self, current):
            snapshots.append(current)
            return {"closed": 1}

    def create(*, cdp_endpoint, target_url):
        targets.append(target_url)
        return Solver()

    monkeypatch.setattr(scope, "fetch_json", fetch)
    monkeypatch.setattr(scope, "_create_scope_solver", create)
    result = scope.compact_active_challenge_pages(
        "http://cdp.test",
        {
            "scopes": {
                "seed": {"challenge_id": "s", "last_request": {"target_url": "seed"}},
                "detail": {
                    "challenge_id": "d",
                    "last_request": {"target_url": "detail"},
                },
            }
        },
    )
    assert targets == ["seed", "detail"]
    assert snapshots == [tabs, tabs]
    assert result["closed"] == 2


@pytest.mark.parametrize("name", ["notify_manual_challenge", "notify_solver_blocked"])
def test_reports_keep_failure_envelope_and_skip_unsafe_targets(monkeypatch, name):
    calls = []

    def post(*_args, **_kwargs):
        calls.append(True)
        raise RuntimeError("transport failed")

    monkeypatch.setattr(scope, "post_json", post)
    report = getattr(scope, name)
    tail = ({},) if name == "notify_solver_blocked" else ()
    result = report(
        "https://api.test/api", {"last_request": {"url": "https://other.test"}}, *tail
    )
    assert result == {"ok": False, "error": "missing_safe_target_url"}
    assert calls == []
    result = report(
        "https://api.test/api",
        {"last_request": {"url": "https://sf.taobao.com/list/example.htm"}},
        *tail,
    )
    assert result == {"ok": False, "error": "RuntimeError('transport failed')"}
    assert calls == [True]
