from tools import (
    pc2_solver_auth,
    pc2_solver_auth_pending,
    pc2_solver_retry_state,
    pc2_solver_state_store,
)
from tools import pc2_solver_cdp
from tools.test.pc2_local_solver_test_context import *
from tools.test.pc2_loop_test_dependencies import patch_loop_dependency


def test_authenticated_target_probe_rejects_route_challenge_beside_exact_healthy_page(
    monkeypatch,
) -> None:
    summaries = iter(
        [
            {
                "authenticatedPage": True,
                "challengePresent": False,
                "loginRequired": False,
            },
            {
                "authenticatedPage": False,
                "challengePresent": True,
                "loginRequired": False,
            },
        ]
    )

    class FakeSolver:
        def __init__(self, *, cdp_endpoint, target_url):
            self.target_url = target_url

        def _normalize_target_url(self, value):
            return str(value)

        def _solver_target_route(self, value):
            return str(value).split("/_____tmd_____/", 1)[0].split("?", 1)[0]

        def _remember_target_tab(self, _tab):
            return None

        def _connect_to_target(self, _ws_url, _title):
            return True

        def _page_challenge_summary(self):
            return next(summaries)

        def _close_solver_ws(self):
            return None

    monkeypatch.setattr(pc2_solver_cdp, "_create_probe_solver", FakeSolver)
    monkeypatch.setattr(
        pc2_solver_cdp,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "healthy",
                "type": "page",
                "url": "https://example.test/list?marker=1",
                "webSocketDebuggerUrl": "ws://example.test/healthy",
            },
            {
                "id": "challenge",
                "type": "page",
                "url": "https://example.test/list/_____tmd_____/punish?x5secdata=redacted",
                "webSocketDebuggerUrl": "ws://example.test/challenge",
            },
        ],
    )

    assert (
        pc2_local_solver.check_cdp_browser_for_authenticated_target(
            "http://127.0.0.1:9223",
            "https://example.test/list?marker=1",
        )
        is None
    )


def test_authenticated_target_probe_accepts_healthy_session_after_target_tab_is_gone(
    monkeypatch,
) -> None:
    summaries = iter(
        [
            {
                "authenticatedPage": True,
                "challengePresent": False,
                "loginRequired": False,
            },
            {
                "authenticatedPage": False,
                "challengePresent": False,
                "loginRequired": False,
            },
        ]
    )

    class FakeSolver:
        def __init__(self, *, cdp_endpoint, target_url):
            self.target_url = target_url

        def _normalize_target_url(self, value):
            return str(value)

        def _solver_target_route(self, value):
            return str(value).split("?", 1)[0]

        def _remember_target_tab(self, _tab):
            return None

        def _connect_to_target(self, _ws_url, _title):
            return True

        def _page_challenge_summary(self):
            return next(summaries)

        def _close_solver_ws(self):
            return None

    monkeypatch.setattr(pc2_solver_cdp, "_create_probe_solver", FakeSolver)
    monkeypatch.setattr(
        pc2_solver_cdp,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "healthy-auction",
                "type": "page",
                "url": "https://example.test/another-list",
                "webSocketDebuggerUrl": "ws://example.test/healthy",
            },
            {
                "id": "neutral-page",
                "type": "page",
                "url": "about:blank",
                "webSocketDebuggerUrl": "ws://example.test/blank",
            },
        ],
    )

    result = pc2_local_solver.check_cdp_browser_for_authenticated_target(
        "http://127.0.0.1:9223",
        "https://example.test/requested-list",
    )

    assert result is not None
    assert result["_target_id"] == "healthy-auction"


def test_success_pending_state_keeps_attempt_window_until_nas_confirmation(
    monkeypatch, tmp_path
) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "consecutive_failures": 10,
            "slider_attempts": 10,
            "solver_cooldown_until": 2000.0,
            "solver_cooldown_reason": "repeated_solver_failures",
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(pc2_solver_state_store, "FALLBACK_STATE_PATH", state_path)

    pending = pc2_local_solver._mark_auth_complete_pending("https://example.test/list")

    assert pending["auth_complete_pending"] is True
    assert pending["consecutive_failures"] == 10
    assert pending["slider_attempts"] == 10
    assert pending["solver_cooldown_until"] == 2000.0
    assert pending["solver_cooldown_reason"] == "repeated_solver_failures"


def test_notify_auth_complete_retries_with_same_completion_id(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    completion_id = "pc2-completion-1"

    def fake_post(_url, payload, *, timeout):
        calls.append({"payload": dict(payload), "timeout": timeout})
        if len(calls) == 1:
            raise TimeoutError("NAS response timeout")
        return _confirmed_auth_payload(completion_id)

    monkeypatch.setattr(pc2_solver_auth, "AUTH_COMPLETE_REQUEST_ATTEMPTS", 3)
    monkeypatch.setattr(pc2_solver_auth, "AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(pc2_solver_auth, "post_json", fake_post)

    result = pc2_local_solver.notify_auth_complete(
        "http://nas/api", completion_id=completion_id
    )

    assert result["request_attempts"] == 2
    assert result["auth_state_confirmed"] is True
    assert [call["payload"]["completion_id"] for call in calls] == [
        completion_id,
        completion_id,
    ]


def test_notify_resume_after_cooldown_carries_node_identity(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(_url, payload, *, timeout):
        captured.update({"payload": dict(payload), "timeout": timeout})
        return _confirmed_resume_payload("pc2-resume-identity")

    monkeypatch.setenv("FAPAI_NODE_ID", "pc2")
    monkeypatch.setenv("FAPAI_REPORT_CDP_ENDPOINT", "http://192.168.15.104:9224")
    monkeypatch.setattr(pc2_solver_auth, "post_json", fake_post)

    result = pc2_local_solver.notify_collection_resume_after_cooldown(
        "http://nas/api",
        "pc2-resume-identity",
        challenge_id="detail-challenge",
        scope="detail",
    )

    assert result["auth_state_confirmed"] is True
    assert captured["payload"] == {
        "source": "pc2_local_solver",
        "resume_request_id": "pc2-resume-identity",
        "challenge_id": "detail-challenge",
        "scope": "detail",
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
    }


def test_auth_complete_requires_explicit_matching_nas_confirmation() -> None:
    completion_id = "pc2-completion-2"

    assert (
        pc2_local_solver._auth_complete_response_confirmed(
            {"ok": True, "completion_id": completion_id},
            completion_id,
        )
        is False
    )
    assert (
        pc2_local_solver._auth_complete_response_confirmed(
            _confirmed_auth_payload("different-id"),
            completion_id,
        )
        is False
    )
    assert (
        pc2_local_solver._auth_complete_response_confirmed(
            _confirmed_auth_payload(completion_id),
            completion_id,
        )
        is True
    )


def test_pending_auth_confirmation_survives_timeout(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "auth_complete_pending": True,
            "auth_completion_id": "pc2-completion-3",
            "auth_complete_next_retry_at": 1000.0,
        }
    )

    monkeypatch.setattr(pc2_solver_state_store, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(pc2_solver_retry_state, "AUTH_COMPLETE_RETRY_BASE_SECONDS", 5.0)
    monkeypatch.setattr(pc2_solver_retry_state, "AUTH_COMPLETE_RETRY_MAX_SECONDS", 60.0)
    monkeypatch.setattr(
        pc2_solver_auth_pending,
        "notify_auth_complete",
        lambda *_args, **_kwargs: {
            "ok": False,
            "error": "read timeout",
            "request_attempts": 3,
        },
    )

    result = pc2_local_solver._retry_pending_auth_confirmation(
        "http://nas/api", state=state, now=1000.0
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["pending"] is True
    assert result["confirmed"] is False
    assert persisted["auth_complete_pending"] is True
    assert persisted["auth_completion_id"] == "pc2-completion-3"
    assert persisted["auth_complete_attempts"] == 3
    assert persisted["auth_complete_next_retry_at"] == 1020.0


def test_expired_auth_confirmation_yields_to_active_challenge(
    monkeypatch, tmp_path
) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "challenge_id": "challenge-current",
            "slider_attempts": 2,
            "last_success_at": 800.0,
            "auth_complete_pending": True,
            "auth_completion_id": "pc2-completion-stale",
            "auth_complete_next_retry_at": 1100.0,
        }
    )
    monkeypatch.setattr(pc2_solver_state_store, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(
        pc2_solver_auth_pending, "AUTH_COMPLETE_PENDING_MAX_SECONDS", 120.0
    )
    monkeypatch.setattr(
        pc2_solver_auth_pending,
        "read_solver_status",
        lambda _api: {
            "paused": True,
            "manual_required": True,
            "challenge_id": "challenge-current",
        },
    )
    monkeypatch.setattr(
        pc2_solver_auth_pending,
        "notify_auth_complete",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "expired confirmation must yield before another completion request"
            )
        ),
    )

    result = pc2_local_solver._retry_pending_auth_confirmation(
        "http://nas/api",
        state=state,
        now=1000.0,
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["superseded"] is True
    assert result["reason"] == "active_challenge_after_auth_confirmation_timeout"
    assert result["pending"] is False
    assert persisted["auth_complete_pending"] is False
    assert persisted["auth_completion_id"] is None
    assert persisted["last_success_at"] is None
    assert persisted["challenge_id"] == "challenge-current"
    assert persisted["slider_attempts"] == 2


def test_pending_auth_confirmation_clears_only_after_explicit_confirmation(
    monkeypatch, tmp_path
) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    completion_id = "pc2-completion-4"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "auth_complete_pending": True,
            "auth_completion_id": completion_id,
            "auth_complete_next_retry_at": 1000.0,
        }
    )

    monkeypatch.setattr(pc2_solver_state_store, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(
        pc2_solver_auth_pending,
        "notify_auth_complete",
        lambda *_args, **_kwargs: {
            **_confirmed_auth_payload(completion_id),
            "request_attempts": 1,
        },
    )

    result = pc2_local_solver._retry_pending_auth_confirmation(
        "http://nas/api", state=state, now=1000.0
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["confirmed"] is True
    assert result["pending"] is False
    assert persisted["auth_complete_pending"] is False
    assert persisted["auth_completion_id"] is None


def test_pending_confirmation_is_processed_before_another_solver_run(
    monkeypatch,
) -> None:
    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)
    patch_loop_dependency(
        monkeypatch,
        "_retry_pending_auth_confirmation",
        lambda _api: {"pending": True, "attempted": False, "confirmed": False},
    )
    patch_loop_dependency(
        monkeypatch,
        "read_solver_status",
        lambda _api: (_ for _ in ()).throw(
            AssertionError("status must not be read while confirmation is pending")
        ),
    )
    patch_loop_dependency(
        monkeypatch,
        "run_solver_local_with_deadline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("solver must not run while confirmation is pending")
        ),
    )
    monkeypatch.setattr(
        pc2_local_solver.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(SystemExit()),
    )

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)


def test_confirmed_auth_completion_reloads_status_before_solver_decision(
    monkeypatch,
) -> None:
    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)
    patch_loop_dependency(
        monkeypatch,
        "_retry_pending_auth_confirmation",
        lambda _api: {"pending": False, "attempted": True, "confirmed": True},
    )
    patch_loop_dependency(
        monkeypatch,
        "read_solver_status",
        lambda _api: (_ for _ in ()).throw(
            AssertionError("status must be read on the next loop")
        ),
    )
    monkeypatch.setattr(
        pc2_local_solver.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(SystemExit()),
    )

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)


def test_confirmed_auth_completion_suppresses_immediate_periodic_cdp_probe(
    monkeypatch,
) -> None:
    confirmation_results = iter(
        [
            {"pending": False, "attempted": True, "confirmed": True},
            {"pending": False, "attempted": False, "confirmed": False},
        ]
    )
    state = pc2_local_solver._default_fallback_state()
    monkeypatch.setattr(pc2_solver_auth, "POST_AUTH_CDP_PROBE_GRACE_SECONDS", 90.0)
    monkeypatch.setattr(pc2_local_solver.time, "time", lambda: 1000.0)
    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)
    patch_loop_dependency(
        monkeypatch,
        "_retry_pending_auth_confirmation",
        lambda _api: next(confirmation_results),
    )
    patch_loop_dependency(
        monkeypatch,
        "_retry_pending_collection_resume",
        lambda _api: {"pending": False, "attempted": False, "confirmed": False},
    )
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
            AssertionError("periodic probe must be suppressed during post-auth grace")
        ),
    )

    def stop_after_next_poll(seconds: float) -> None:
        if seconds > 0:
            raise SystemExit

    monkeypatch.setattr(pc2_local_solver.time, "sleep", stop_after_next_poll)

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=30)
