from tools import (
    pc2_solver_fallback,
    pc2_solver_retry_state,
    pc2_solver_scope,
    pc2_solver_state_store,
)
from tools import pc2_solver_execution
from tools.test.pc2_local_solver_test_context import *
from tools.test.pc2_loop_test_dependencies import patch_loop_dependency


def test_close_stale_challenge_probe_target_preserves_keepalive(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    class FakeSolver:
        @staticmethod
        def _is_manual_challenge_url(value):
            return "/_____tmd_____/punish" in str(value or "")

        def __init__(self, *, cdp_endpoint, target_url):
            calls.append(("init", f"{cdp_endpoint}|{target_url}"))

        def _open_keepalive_tab(self):
            calls.append(("open", None))
            return "keepalive-1"

        def _close_cdp_target(self, target_id):
            calls.append(("close", target_id))
            return True

    monkeypatch.setattr(pc2_solver_execution, "_solver_class", lambda: FakeSolver)
    monkeypatch.setattr(
        pc2_solver_execution, "fetch_json", lambda *_args, **_kwargs: []
    )

    result = pc2_local_solver.close_stale_challenge_probe_target(
        "http://127.0.0.1:9223",
        {
            "_target_id": "challenge-1",
            "_target_url": "https://sf.taobao.com/list/page/_____tmd_____/punish?x5step=1",
        },
    )

    assert result == {
        "attempted": True,
        "closed": True,
        "target_id": "challenge-1",
        "keepalive_opened": True,
        "keepalive_reused": False,
    }
    assert calls == [
        (
            "init",
            "http://127.0.0.1:9223|https://sf.taobao.com/list/page/_____tmd_____/punish?x5step=1",
        ),
        ("open", None),
        ("close", "challenge-1"),
    ]


def test_close_challenge_pages_for_scope_closes_only_seed_tabs(monkeypatch) -> None:
    calls: list[str] = []
    closed_targets: list[str] = []
    tabs = [
        {
            "id": "seed-page",
            "type": "page",
            "url": "https://sf.taobao.com//list/50025969__2.htm",
        },
        {
            "id": "seed-challenge",
            "type": "page",
            "url": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?x5step=1",
        },
        {
            "id": "detail-page",
            "type": "page",
            "url": "https://sf-item.taobao.com/sf_item/570192626894.htm",
        },
        {
            "id": "detail-challenge",
            "type": "page",
            "url": "https://sf-item.taobao.com/sf_item/570192626894.htm/_____tmd_____/punish?x5step=1",
        },
        {
            "id": "login",
            "type": "page",
            "url": "https://login.taobao.com/member/login.jhtml",
        },
        {"id": "blank", "type": "page", "url": "about:blank"},
    ]

    def fake_fetch(url: str, timeout: int):
        calls.append(url)
        return tabs

    class FakeSolver:
        def __init__(self, *, cdp_endpoint):
            assert cdp_endpoint == "http://127.0.0.1:9223"

        def _close_cdp_target(self, target_id):
            closed_targets.append(target_id)
            return True

    monkeypatch.setattr(pc2_solver_scope, "fetch_json", fake_fetch)
    monkeypatch.setattr(pc2_solver_scope, "_create_scope_solver", FakeSolver)

    result = pc2_local_solver.close_challenge_pages_for_scope(
        "http://127.0.0.1:9223", "seed"
    )

    assert result == {
        "attempted": True,
        "closed": 2,
        "target_ids": ["seed-page", "seed-challenge"],
        "scope": "seed",
    }
    assert calls == [
        "http://127.0.0.1:9223/json/list",
    ]
    assert closed_targets == ["seed-page", "seed-challenge"]


def test_compact_active_challenge_pages_keeps_one_page_per_scope(monkeypatch) -> None:
    closed_targets: list[str] = []
    tabs = [
        {
            "id": "seed-1",
            "type": "page",
            "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5step=1",
            "webSocketDebuggerUrl": "ws://seed-1",
        },
        {
            "id": "seed-2",
            "type": "page",
            "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5step=2",
            "webSocketDebuggerUrl": "ws://seed-2",
        },
        {
            "id": "detail-1",
            "type": "page",
            "url": "https://sf-item.taobao.com//sf_item/570192626894.htm/_____tmd_____/punish?x5step=1",
            "webSocketDebuggerUrl": "ws://detail-1",
        },
        {
            "id": "detail-2",
            "type": "page",
            "url": "https://sf-item.taobao.com//sf_item/570192626894.htm/_____tmd_____/punish?x5step=2",
            "webSocketDebuggerUrl": "ws://detail-2",
        },
    ]

    def fake_fetch(_url: str, timeout: int):
        assert timeout == 5
        return [tab for tab in tabs if tab["id"] not in closed_targets]

    def fake_close(_solver, target_id):
        closed_targets.append(target_id)
        return True

    monkeypatch.setattr(pc2_solver_scope, "fetch_json", fake_fetch)
    monkeypatch.setattr(pc2_local_solver.CaptchaSolver, "_close_cdp_target", fake_close)

    result = pc2_local_solver.compact_active_challenge_pages(
        "http://127.0.0.1:9223",
        {
            "scopes": {
                "seed": {
                    "challenge_id": "seed-challenge",
                    "last_request": {
                        "target_url": "https://sf.taobao.com/list/50025969__2.htm"
                    },
                },
                "detail": {
                    "challenge_id": "detail-challenge",
                    "last_request": {
                        "target_url": "https://sf-item.taobao.com/sf_item/570192626894.htm"
                    },
                },
            }
        },
    )

    assert result["closed"] == 2
    assert set(result["scopes"]) == {"seed", "detail"}
    assert set(closed_targets) == {"seed-2", "detail-2"}


def test_close_stale_challenge_probe_target_reuses_existing_keepalive(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    class FakeSolver:
        @staticmethod
        def _is_manual_challenge_url(value):
            return "/_____tmd_____/punish" in str(value or "")

        def __init__(self, *, cdp_endpoint, target_url):
            calls.append(("init", f"{cdp_endpoint}|{target_url}"))

        def _open_keepalive_tab(self):
            raise AssertionError("an existing keepalive must be reused")

        def _close_cdp_target(self, target_id):
            calls.append(("close", target_id))
            return True

    monkeypatch.setattr(pc2_solver_execution, "_solver_class", lambda: FakeSolver)
    monkeypatch.setattr(
        pc2_solver_execution,
        "fetch_json",
        lambda *_args, **_kwargs: [
            {"id": "blank-1", "type": "page", "url": "about:blank"},
            {"id": "challenge-1", "type": "page", "url": "https://example.test/punish"},
        ],
    )

    result = pc2_local_solver.close_stale_challenge_probe_target(
        "http://127.0.0.1:9223",
        {
            "_target_id": "challenge-1",
            "_target_url": "https://sf.taobao.com/list/_____tmd_____/punish?x5step=1",
        },
    )

    assert result == {
        "attempted": True,
        "closed": True,
        "target_id": "challenge-1",
        "keepalive_opened": False,
        "keepalive_reused": True,
    }
    assert calls[-1] == ("close", "challenge-1")


def test_close_stale_challenge_probe_target_does_not_close_normal_page(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        pc2_local_solver.CaptchaSolver,
        "_is_manual_challenge_url",
        lambda _value: False,
    )
    monkeypatch.setattr(
        pc2_local_solver.CaptchaSolver,
        "_close_cdp_target",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("normal target must stay open")
        ),
    )

    result = pc2_local_solver.close_stale_challenge_probe_target(
        "http://127.0.0.1:9223",
        {
            "_target_id": "normal-1",
            "_target_url": "https://sf.taobao.com/list/page=1",
        },
    )

    assert result == {
        "attempted": False,
        "closed": False,
        "reason": "target_not_challenge",
    }


def test_resolve_stale_challenge_probe_target_after_resume_rebuilds_lost_target(
    monkeypatch,
) -> None:
    requested_url = "https://sf.taobao.com/list/page=1"
    recovered_target = {
        "_target_id": "challenge-after-restart",
        "_target_url": "https://sf.taobao.com/list/_____tmd_____/punish?x5step=1",
    }
    calls: list[str] = []

    def fake_check(_endpoint, *, target_url=None):
        calls.append(target_url)
        return recovered_target

    monkeypatch.setattr(
        pc2_solver_execution, "check_cdp_browser_for_challenge_page", fake_check
    )

    result = pc2_local_solver.resolve_stale_challenge_probe_target_after_resume(
        "http://127.0.0.1:9223",
        None,
        {
            "confirmed": True,
            "result": _confirmed_resume_payload(
                "pc2-resume-restart", target_url=requested_url
            ),
        },
    )

    assert result == recovered_target
    assert calls == [requested_url]


def test_resolve_stale_challenge_probe_target_after_resume_refreshes_rotated_target(
    monkeypatch,
) -> None:
    rotated_target = {
        "_target_id": "rotated-detail",
        "_target_url": "https://sf-item.taobao.com/sf_item/570192626894.htm?__captcha_solver_bg=1",
    }
    refreshed_target = {
        "_target_id": "rotated-detail",
        "_target_url": "https://sf-item.taobao.com/_____tmd_____/punish?x5step=1",
        "_challenge_evidence": ["challengePresent"],
    }
    calls: list[str | None] = []

    def fake_check(_endpoint, *, target_url=None):
        calls.append(target_url)
        return refreshed_target

    monkeypatch.setattr(
        pc2_solver_execution, "check_cdp_browser_for_challenge_page", fake_check
    )

    result = pc2_local_solver.resolve_stale_challenge_probe_target_after_resume(
        "http://127.0.0.1:9223",
        rotated_target,
        {"confirmed": True},
    )

    assert result == refreshed_target
    assert calls == [rotated_target["_target_url"]]


def test_resolve_stale_challenge_probe_target_after_resume_keeps_unverified_target(
    monkeypatch,
) -> None:
    rotated_target = {
        "_target_id": "normal-detail",
        "_target_url": "https://sf-item.taobao.com/sf_item/570192626894.htm",
    }
    monkeypatch.setattr(
        pc2_solver_execution,
        "check_cdp_browser_for_challenge_page",
        lambda _endpoint, *, target_url=None: None,
    )

    result = pc2_local_solver.resolve_stale_challenge_probe_target_after_resume(
        "http://127.0.0.1:9223",
        rotated_target,
        {"confirmed": True},
    )

    assert result == rotated_target


def test_confirmed_cooldown_resume_suppresses_immediate_periodic_cdp_probe(
    monkeypatch,
) -> None:
    requested_url = "https://sf.taobao.com/list/page=1"
    recovered_target = {
        "_target_id": "challenge-after-restart",
        "_target_url": "https://sf.taobao.com/list/_____tmd_____/punish?x5step=1",
    }
    resume_results = iter(
        [
            {
                "pending": False,
                "attempted": True,
                "confirmed": True,
                "result": _confirmed_resume_payload(
                    "pc2-resume-restart",
                    target_url=requested_url,
                ),
            },
            {"pending": False, "attempted": False, "confirmed": False},
        ]
    )
    cleanup_targets: list[dict[str, object] | None] = []
    state = pc2_local_solver._default_fallback_state()
    from tools import pc2_solver_auth

    monkeypatch.setattr(pc2_solver_auth, "POST_AUTH_CDP_PROBE_GRACE_SECONDS", 90.0)
    monkeypatch.setattr(pc2_local_solver.time, "time", lambda: 1000.0)
    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)
    patch_loop_dependency(
        monkeypatch,
        "_retry_pending_auth_confirmation",
        lambda _api: {"pending": False, "attempted": False, "confirmed": False},
    )
    patch_loop_dependency(
        monkeypatch,
        "_retry_pending_collection_resume",
        lambda _api: next(resume_results),
    )
    monkeypatch.setattr(
        pc2_solver_execution,
        "check_cdp_browser_for_challenge_page",
        lambda _endpoint, *, target_url=None: (
            recovered_target if target_url == requested_url else None
        ),
    )

    def fake_close(_endpoint, target):
        cleanup_targets.append(target)
        return {"attempted": True, "closed": True}

    patch_loop_dependency(monkeypatch, "close_stale_challenge_probe_target", fake_close)
    patch_loop_dependency(
        monkeypatch,
        "read_solver_status",
        lambda _api: {
            "paused": False,
            "running": False,
            "manual_required": False,
            "challenge_id": None,
            "last_request": {
                "node_id": "pc2",
                "target_url": "https://example.test/requested-page",
            },
        },
    )
    patch_loop_dependency(monkeypatch, "_load_fallback_state", lambda: dict(state))
    patch_loop_dependency(monkeypatch, "_save_fallback_state", lambda _state: None)
    patch_loop_dependency(
        monkeypatch,
        "_sync_challenge_state",
        lambda value, _challenge, scope=None: (value, False),
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_slider",
        lambda _endpoint, **_kwargs: (_ for _ in ()).throw(
            AssertionError("periodic probe must be suppressed after cooldown resume")
        ),
    )

    def stop_after_next_poll(seconds: float) -> None:
        if seconds > 0:
            raise SystemExit

    monkeypatch.setattr(pc2_local_solver.time, "sleep", stop_after_next_poll)

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=30)

    assert cleanup_targets == [recovered_target]


def test_resume_after_cooldown_timeout_keeps_same_request_id(
    monkeypatch, tmp_path
) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "slider_attempts": 10,
            "consecutive_failures": 10,
            "solver_cooldown_until": 1000.0,
            "solver_cooldown_reason": "repeated_solver_failures",
        }
    )
    monkeypatch.setattr(pc2_solver_state_store, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(pc2_solver_retry_state, "AUTH_COMPLETE_RETRY_BASE_SECONDS", 5.0)
    monkeypatch.setattr(pc2_solver_retry_state, "AUTH_COMPLETE_RETRY_MAX_SECONDS", 60.0)

    pending = pc2_local_solver._mark_collection_resume_pending(state, now=1000.0)
    request_id = pending["collection_resume_request_id"]
    monkeypatch.setattr(
        pc2_solver_fallback,
        "notify_collection_resume_after_cooldown",
        lambda *_args, **_kwargs: {
            "ok": False,
            "error": "read timeout",
            "request_attempts": 2,
        },
    )

    result = pc2_local_solver._retry_pending_collection_resume(
        "http://nas/api",
        state=pending,
        now=1000.0,
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["pending"] is True
    assert result["confirmed"] is False
    assert persisted["collection_resume_request_id"] == request_id
    assert persisted["collection_resume_attempts"] == 2
    assert persisted["collection_resume_next_retry_at"] == 1010.0
    assert persisted["slider_attempts"] == 10
    assert persisted["solver_cooldown_until"] == 1000.0
